#!/usr/bin/env python3
# -* encoding: utf-8 *-

import sys
import os.path
import os
import time
import tempfile
import hashlib
import zlib
import logging
import json

import requests
from esptool import ESPLoader, erase_flash, write_flash

import airrohrFlasher
from airrohrFlasher.qtvariant import QtGui, QtCore, QtWidgets
from airrohrFlasher.utils import QuickThread
from airrohrFlasher.workers import PortDetectThread, FirmwareListThread, \
    ZeroconfDiscoveryThread

from gui import mainwindow

from airrohrFlasher.consts import UPDATE_REPOSITORY, ALLOWED_PROTO, \
    PREFERED_PORTS, ROLE_DEVICE, DRIVERS_URL

import spiffsGen
from spiffsGen import spiffsgen
#from spiffsgen import _____________

if getattr(sys, 'frozen', False):
    RESOURCES_PATH = sys._MEIPASS
else:
    RESOURCES_PATH = os.path.dirname(os.path.realpath(__file__))


class MainWindow(QtWidgets.QMainWindow, mainwindow.Ui_MainWindow):
    uploadProgress = QtCore.Signal([str, int])
    errorSignal = QtCore.Signal([str])
    uploadThread = None
    zeroconf_discovery = None
    boards_detected = False
    jsonFinal = ""
    spiffsBinary = b'' 

    def __init__(self, parent=None, app=None):
        super(MainWindow, self).__init__(parent)
        self.setWindowFlags(QtCore.Qt.Dialog)

        # FIXME: dirty hack to solve relative paths in *.ui
        oldcwd = os.getcwd()
        os.chdir(os.path.join(RESOURCES_PATH, 'assets'))
        self.setupUi(self)
        os.chdir(oldcwd)

        self.app = app

        self.translator = QtCore.QTranslator()
        self.i18n_init(QtCore.QLocale.system())

        self.statusbar.showMessage(self.tr("Loading firmware list..."))

        self.versionBox.clear()
        self.firmware_list = FirmwareListThread()
        self.firmware_list.listLoaded.connect(self.populate_versions)
        self.firmware_list.error.connect(self.on_work_error)
        self.firmware_list.start()

        self.port_detect = PortDetectThread()
        self.port_detect.portsUpdate.connect(self.populate_boards)
        self.port_detect.error.connect(self.on_work_error)
        self.port_detect.start()

        self.discovery_start()

        self.globalMessage.hide()

        # Hide WIP GUI parts...
        self.on_expertModeBox_clicked()
        self.expertModeBox.hide()
        self.tabWidget.removeTab(self.tabWidget.indexOf(self.serialTab))

        self.uploadProgress.connect(self.on_work_update)
        self.errorSignal.connect(self.on_work_error)

        self.cachedir = tempfile.TemporaryDirectory()
        self.cachedirjson = tempfile.TemporaryDirectory()
        self.cachedirspiffs = tempfile.TemporaryDirectory()

        print(self.cachedir.name)
        print(self.cachedirjson.name)
        print(self.cachedirspiffs.name)




    def show_global_message(self, title, message):
        self.globalMessage.show()
        self.globalMessageTitle.setText(title)
        self.globalMessageText.setText(message)

    def on_work_update(self, status, progress):
        self.statusbar.showMessage(status)
        self.progressBar.setValue(progress)

    def on_work_error(self, message):
        self.statusbar.showMessage(message)

    @property
    def version(self):
        return airrohrFlasher.__version__

    @property
    def build_id(self):
        try:
            from airrohrFlasher._buildid import commit, builddate
        except ImportError:
            import datetime
            commit = 'devel'
            builddate = datetime.datetime.now().strftime('%Y%m%d')

        return '{}-{}/{}'.format(self.version, commit, builddate)

    def i18n_init(self, locale):
        """Initializes i18n to specified QLocale"""

        self.app.removeTranslator(self.translator)
        lang = QtCore.QLocale.languageToString(locale.language())
        self.translator.load(os.path.join(
            RESOURCES_PATH, 'i18n', lang + '.qm'))
        self.app.installTranslator(self.translator)
        self.retranslateUi(self)

    def retranslateUi(self, win):
        super(MainWindow, self).retranslateUi(win)

        win.setWindowTitle(win.windowTitle().format(
            version=self.version))
        win.buildLabel.setText(win.buildLabel.text().format(
            build_id=self.build_id))

    def populate_versions(self, files):
        """Loads available firmware versions into versionbox widget"""

        for fname in files:
            if not fname.endswith('.bin'):
                continue

            item = QtGui.QStandardItem(fname)
            item.setData(UPDATE_REPOSITORY + fname, ROLE_DEVICE)
            self.versionBox.model().appendRow(item)

        self.statusbar.clearMessage()

    def populate_boards(self, ports):
        """Populates board selection combobox from list of pyserial
        ListPortInfo objects"""

        self.boardBox.clear()

        prefered, others = self.group_ports(ports)

        for b in prefered:
            item = QtGui.QStandardItem(
                '{0.description} ({0.device})'.format(b))
            item.setData(b.device, ROLE_DEVICE)
            self.boardBox.model().appendRow(item)

        if not prefered:
            sep = QtGui.QStandardItem(self.tr('No boards found'))
            sep.setEnabled(False)
            self.boardBox.model().appendRow(sep)

            # No prefered boards has been found so far and there is a
            # suggested driver download URL available
            if not self.boards_detected and DRIVERS_URL:
                self.show_global_message(
                    self.tr('No boards found'),
                    self.tr('Have you installed <a href="{drivers_url}">'
                            'the drivers</a>?').format(drivers_url=DRIVERS_URL))
        else:
            self.globalMessage.hide()
            self.boards_detected = True

        if others:
            sep = QtGui.QStandardItem(self.tr('Others...'))
            sep.setEnabled(False)
            self.boardBox.model().appendRow(sep)

        for b in others:
            item = QtGui.QStandardItem(
                '{0.description} ({0.device})'.format(b))
            item.setData(b.device, ROLE_DEVICE)
            self.boardBox.model().appendRow(item)

    def group_ports(self, ports):
        prefered = []
        others = []

        for p in ports:
            if (p.vid, p.pid) in PREFERED_PORTS:
                prefered.append(p)
            else:
                others.append(p)
        return prefered, others


    def is_json(self, myjson):
        try:
            json_object = json.loads(myjson)
        except ValueError as e:
            return False
        return True


        #Credentials saver

    @QtCore.Slot()

    def on_wifiButton_clicked(self):

        self.statusbar.clearMessage()

        ssid = self.wifiSSID.text()
        pw = self.wifiPW.text()

        if not ssid:
            self.statusbar.showMessage(self.tr("No SSID typed."))
            return

        if not pw:
            self.statusbar.showMessage(self.tr("No PW type."))
            return

        jsonPart1 = '{"SOFTWARE_VERSION":"NRZ-2020-133","current_lang":"FR","wlanssid":"'
        jsonPart2 = '","wlanpwd":"'
        jsonPart3 = '","www_username":"admin","www_password":"","fs_ssid":"airRohr-2509507","fs_pwd":"","www_basicauth_enabled":false,"dht_read":false,"htu21d_read":false,"ppd_read":false,"sds_read":false,"pms_read":true,"hpm_read":false,"npm_read":false,"sps30_read":false,"bmp_read":false,"bmx280_read":true,"sht3x_read":false,"ds18b20_read":false,"dnms_read":false,"dnms_correction":"0.0","temp_correction":"0.0","gps_read":false,"send2dusti":true,"ssl_dusti":false,"send2madavi":true,"ssl_madavi":false,"send2sensemap":false,"send2fsapp":false,"send2aircms":false,"send2csv":false,"auto_update":true,"use_beta":false,"has_display":false,"has_sh1106":false,"has_flipped_display":false,"has_lcd1602":false,"has_lcd1602_27":true,"has_lcd2004":false,"has_lcd2004_27":false,"display_wifi_info":true,"display_device_info":true,"debug":3,"sending_intervall_ms":145000,"time_for_wifi_config":600000,"senseboxid":"","send2custom":false,"host_custom":"192.168.234.1","url_custom":"/data.php","port_custom":80,"user_custom":"","pwd_custom":"","ssl_custom":false,"send2influx":false,"host_influx":"influx.server","url_influx":"/write?db=sensorcommunity","port_influx":8086,"user_influx":"","pwd_influx":"","measurement_name_influx":"feinstaub","ssl_influx":false}'
        jsonTest = jsonPart1 + ssid + jsonPart2 + pw + jsonPart3
        
        if not self.is_json(jsonTest):
            self.statusbar.showMessage(self.tr("Created invalid json."))
            return
        else:
            self.jsonFinal = jsonPart1 + ssid + jsonPart2 + pw + jsonPart3
            self.statusbar.showMessage(self.tr("Created valid json."))
            print(self.jsonFinal)
            
            #self.cachedirspiffs = tempfile.TemporaryDirectory()

            self.statusbar.showMessage(self.tr("Opening temporary json directory."))

            jsonfile = open(self.cachedirjson.name + "/config.json", "w")
            self.statusbar.showMessage(self.tr("Write json in temporay json directory."))
            jsonfile.write(self.jsonFinal)
            jsonfile.close()

            #self.cachedirspiffs = tempfile.TemporaryDirectory()

            #python3 spiffsgen.py --page-size 256 --block-size 8192 --no-magic-len --aligned-obj-ix-tables --meta-len=0 $((0xFFA000-0x100000)) path/to/files image.bin

            #args = ["--page-size 256","--block-size 8192","--no-magic-len","--aligned-obj-ix-tables","--meta-len=0 $((0xFFA000-0x100000))", path/to/files image.bin]

            self.statusbar.showMessage(self.tr("Make SPIFFS bin"))

            args = []

            args.extend(["spiffsgen.py",
                     "--page-size", "256",
                     "--block-size", "8192",
                     "--meta-len=0", "0x100000"])

            args.append("--no-magic-len")
            args.append("--aligned-obj-ix-tables")
  
            args.extend([self.cachedirjson.name, self.cachedirspiffs.name + "/spiffs.bin"])

            sys.argv = args
            spiffsgen.main()
            self.statusbar.showMessage(self.tr("spiffs.bin done!"))

            self.statusbar.clearMessage()
            device = self.boardBox.currentData(ROLE_DEVICE)

            if not device:
                self.statusbar.showMessage(self.tr("No device selected."))
                return
            
            self.write_config(self.uploadProgress, device, self.cachedirspiffs.name + "/spiffs.bin")


    def write_config(self, progress, device, path, baudrate=460800):

        progress.emit(self.tr('Connecting...'), 0)
        init_baud = min(ESPLoader.ESP_ROM_BAUD, baudrate)
        esp = ESPLoader.detect_chip(device, init_baud, 'default_reset', False)

        progress.emit(self.tr('Connected. Chip type: {chip_type}').format(
                    chip_type=esp.get_chip_description()), 0)
        esp = esp.run_stub()
        esp.change_baud(baudrate)
        #esp.connect()
        # esp.write_flash(0x300000, spiffs)
        # progress.emit(self.tr('Config written!'), 100)

        #with open(spiffs, 'rb') as fd:
            #uncimagespiffs = fd.read()


        with open(path, 'rb') as fd:
            uncimagespiffs = fd.read()

        imagespiffs = zlib.compress(uncimagespiffs, 0)

        address = 0x300000
        #address = 0x0
        blocks = esp.flash_defl_begin(len(uncimagespiffs), len(imagespiffs), address)


            # ( '.menu.ESPModule.ESP12.build.spiffs_start', '0x300000' ),
            # ( '.menu.ESPModule.ESP12.build.spiffs_end', '0x3FB000' ),
            # ( '.menu.ESPModule.ESP12.build.spiffs_blocksize', '8192' ),
            # ( '.menu.ESPModule.ESP12.build.spiffs_pagesize', '256' ),
            # ( '.menu.ESPModule.ESP12.upload.maximum_size', '1044464' ),

        seq = 0
        written = 0
        t = time.time()
        while len(imagespiffs) > 0:
            current_addr = address + seq * esp.FLASH_WRITE_SIZE
            progress.emit(self.tr('Writing at 0x{address:08x}...').format(
                          address=current_addr),
                          100 * (seq + 1) // blocks)

            block = imagespiffs[0:esp.FLASH_WRITE_SIZE]
            esp.flash_defl_block(block, seq, timeout=3.0)
            imagespiffs = imagespiffs[esp.FLASH_WRITE_SIZE:]
            seq += 1
            written += len(block)
            #print("iteration "+str(seq))


        t = time.time() - t

        progress.emit(self.tr(
            'Finished in {time:.2f} seconds. Sensor ID: {sensor_id}').format(
                time=t, sensor_id=esp.chip_id()), 100)

        esp.flash_finish(True)

    @QtCore.Slot()
    def on_uploadButton_clicked(self):
        self.statusbar.clearMessage()

        device = self.boardBox.currentData(ROLE_DEVICE)
        version = self.versionBox.currentText()

        if not device:
            self.statusbar.showMessage(self.tr("No device selected."))
            return

        if not version:
            self.statusbar.showMessage(self.tr("No version selected."))
            return

        sel = self.versionBox.model().item(
            self.versionBox.currentIndex())
        if sel:
            orig_version = sel.text()
        else:
            orig_version = ''

        if version == orig_version:
            # Editable combobox has been unchanged
            binary_uri = self.versionBox.currentData(ROLE_DEVICE)
        elif version.startswith(ALLOWED_PROTO):
            # User has provided a download URL
            binary_uri = version
        elif os.path.exists(version):
            binary_uri = version
        else:
            self.statusbar.showMessage(self.tr(
                "Invalid version / file does not exist"))
            return

        if self.flash_board.running():
            self.statusbar.showMessage(self.tr("Work in progess..."))
            return

        self.flash_board(self.uploadProgress, device, binary_uri,
                         error=self.errorSignal)

    def cache_download(self, progress, binary_uri):
        """Downloads and caches file with status reports via Qt Signals"""
        cache_fname = os.path.join(
            self.cachedir.name,
            hashlib.sha256(binary_uri.encode('utf-8')).hexdigest())
        
        #print(self.cachedir)

        if os.path.exists(cache_fname):
            return cache_fname

        with open(cache_fname, 'wb') as fd:
            progress.emit(self.tr('Downloading...'), 0)
            response = requests.get(binary_uri, stream=True)
            total_length = response.headers.get('content-length')

            dl = 0
            total_length = int(total_length or 0)
            for data in response.iter_content(chunk_size=4096):
                dl += len(data)
                fd.write(data)

                if total_length:
                    progress.emit(self.tr('Downloading...'),
                                  (100*dl) // total_length)

        return cache_fname

    @QuickThread.wrap
    def erase_board(self, progress, device, baudrate=460800):

        progress.emit(self.tr('Connecting...'), 0)
        init_baud = min(ESPLoader.ESP_ROM_BAUD, baudrate)
        esp = ESPLoader.detect_chip(device, init_baud, 'default_reset', False)

        progress.emit(self.tr('Connected. Chip type: {chip_type}').format(
                      chip_type=esp.get_chip_description()), 0)
        esp = esp.run_stub()
        esp.change_baud(baudrate)
        esp.erase_flash()
        progress.emit(self.tr('Erasing complete!'), 100)

    @QtCore.Slot()
    def on_eraseButton_clicked(self):
        self.statusbar.clearMessage()
        device = self.boardBox.currentData(ROLE_DEVICE)

        if not device:
            self.statusbar.showMessage(self.tr("No device selected."))
            return

        if self.erase_board.running():
            self.statusbar.showMessage(self.tr("Erasing in progress..."))
            return

        self.erase_board(self.uploadProgress, device,
                         error=self.errorSignal)

    @QuickThread.wrap
    def flash_board(self, progress, device, binary_uri, baudrate=460800):

        if binary_uri.startswith(ALLOWED_PROTO):
            binary_uri = self.cache_download(progress, binary_uri)

        progress.emit(self.tr('Connecting...'), 0)

        init_baud = min(ESPLoader.ESP_ROM_BAUD, baudrate)
        esp = ESPLoader.detect_chip(device, init_baud, 'default_reset', False)

        progress.emit(self.tr('Connected. Chip type: {chip_type}').format(
                      chip_type=esp.get_chip_description()), 0)
        esp = esp.run_stub()
        esp.change_baud(baudrate)

        with open(binary_uri, 'rb') as fd:
            uncimage = fd.read()

        image = zlib.compress(uncimage, 9)

        address = 0x0
        blocks = esp.flash_defl_begin(len(uncimage), len(image), address)

        seq = 0
        written = 0
        t = time.time()
        while len(image) > 0:
            current_addr = address + seq * esp.FLASH_WRITE_SIZE
            progress.emit(self.tr('Writing at 0x{address:08x}...').format(
                          address=current_addr),
                          100 * (seq + 1) // blocks)

            block = image[0:esp.FLASH_WRITE_SIZE]
            esp.flash_defl_block(block, seq, timeout=3.0)
            image = image[esp.FLASH_WRITE_SIZE:]
            seq += 1
            written += len(block)
        t = time.time() - t

        progress.emit(self.tr(
            'Finished in {time:.2f} seconds. Sensor ID: {sensor_id}').format(
                time=t, sensor_id=esp.chip_id()), 100)

        esp.flash_finish(True)

    @QtCore.Slot()
    def on_expertModeBox_clicked(self):
        self.expertForm.setVisible(self.expertModeBox.checkState())
        # self.centralwidget.setFixedHeight(
        #     self.centralwidget.sizeHint().height())
        # self.setFixedHeight(self.sizeHint().height())

    # Zeroconf page
    def discovery_start(self):
        if self.zeroconf_discovery:
            self.zeroconf_discovery.stop()

        self.zeroconf_discovery = ZeroconfDiscoveryThread()
        self.zeroconf_discovery.deviceDiscovered.connect(
            self.on_zeroconf_discovered)
        self.zeroconf_discovery.start()

    def on_zeroconf_discovered(self, name, address, info):
        """Called on every zeroconf discovered device"""
        if (name.lower().startswith('feinstaubsensor')
                or name.lower().startswith('nam')
                or name.lower().startswith('smogomierz')
                or name.lower().startswith('airrohr')):
            item = QtWidgets.QListWidgetItem('{}: {}'.format(address, name.split('.')[0]))
            item.setData(ROLE_DEVICE, 'http://{}:{}'.format(address, info.port))
            self.discoveryList.addItem(item)

    @QtCore.Slot(QtWidgets.QListWidgetItem)
    def on_discoveryList_itemDoubleClicked(self, index):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(index.data(ROLE_DEVICE)))

    @QtCore.Slot()
    def on_discoveryRefreshButton_clicked(self):
        self.discoveryList.clear()
        self.discovery_start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(app=app)
    window.show()
    sys.exit(app.exec_())
