############################
# **** IMPORT SECTION **** #
############################
import sys
import os
from telnetlib import NOP
import linuxcnc

from PyQt5 import QtCore, QtWidgets
from qtvcp.widgets.file_manager import FileManager as FM
from qtvcp.widgets.mdi_line import MDILine as MDI_WIDGET
from qtvcp.widgets.gcode_editor import GcodeEditor as GCODE
from qtvcp.widgets.stylesheeteditor import  StyleSheetEditor as SSE
from qtvcp.lib.keybindings import Keylookup
from qtvcp.core import Status, Action, Info, Path, Qhal
from qtvcp.lib.gcodes import GCodes

# Set up logging
from qtvcp import logger
LOG = logger.getLogger(__name__)

# Set the log level for this module
LOG.setLevel(logger.INFO) # One of DEBUG, INFO, WARNING, ERROR, CRITICAL

PATH = Path()

###########################################
# **** instantiate libraries section **** #
###########################################

KEYBIND = Keylookup()
STATUS = Status()
ACTION = Action()
STYLEEDITOR = SSE()

QHAL = Qhal()
INFO = Info()

DEFAULT = 0
WARNING = 1
CRITICAL = 2


###################################
# **** HANDLER CLASS SECTION **** #
###################################

class HandlerClass:

    ########################
    # **** INITIALIZE **** #
    ########################
    # widgets allows access to  widgets from the qtvcp files
    # at this point the widgets and hal pins are not instantiated
    def __init__(self, halcomp,widgets,paths):
        self.hal = halcomp
        self.w = widgets
        # self.PATHS = paths
        self.gcodes = GCodes(widgets)
        #self.valid = QtGui.QDoubleValidator(-999.999, 999.999, 3)
        #KEYBIND.add_call('Key_F11','on_keycall_F11')
        #KEYBIND.add_call('Key_F12','on_keycall_F12')
        KEYBIND.add_call('Key_Pause', 'on_keycall_pause')

        # Global variables
        self.probe = None
        self.default_setup = os.path.join(PATH.CONFIGPATH, "default_setup.html")
        self.docs = os.path.join(PATH.SCREENDIR, PATH.BASEPATH,'docs/getting_started.html')
        self.start_line = 0
        self.run_time = 0
        self.time_tenths = 0
        self.timer_on = False
        self.home_all = False
        self.min_spindle_rpm = INFO.MIN_SPINDLE_SPEED
        self.max_spindle_rpm = INFO.MAX_SPINDLE_SPEED
        self.system_list = ["G54","G55","G56","G57","G58","G59","G59.1","G59.2","G59.3"]
        self.slow_jog_factor = 10
        self.reload_tool = 0
        self.last_loaded_program = ""
        self.first_turnon = True
        
        self.auto_list = ["chk_eoffsets", "cmb_gcode_history"]
        self.auto_list = ["chk_eoffsets"]
        self.button_response_list = ["btn_start", "btn_home_all"]
        self.system_list = ["G54","G55","G56","G57","G58","G59","G59.1","G59.2","G59.3"]
        # STATUS CONNECT
        #STATUS.connect('general', self.dialog_return)
        STATUS.connect('state-on', lambda w: self.enable_onoff(True))
        STATUS.connect('state-off', lambda w: self.enable_onoff(False))
        STATUS.connect('mode-manual', lambda w: self.enable_auto(True))
        STATUS.connect('mode-mdi', lambda w: self.enable_auto(True))
        STATUS.connect('mode-auto', lambda w: self.enable_auto(False))
        STATUS.connect('interp-run', lambda w: self.set_button_response_state(True))
        STATUS.connect('interp-idle', lambda w: self.set_button_response_state(False))
        STATUS.connect('gcode-line-selected', lambda w, line: self.set_start_line(line))
        STATUS.connect('graphics-line-selected', lambda w, line: self.set_start_line(line))
        STATUS.connect('hard-limits-tripped', self.hard_limit_tripped)
        STATUS.connect('program-pause-changed', lambda w, state: self.w.btn_spindle_pause.setEnabled(state))
        STATUS.connect('actual-spindle-speed-changed', lambda w, speed: self.update_rpm(speed))
        STATUS.connect('user-system-changed', lambda w, data: self.user_system_changed(data))
        STATUS.connect('metric-mode-changed', lambda w, mode: self.metric_mode_changed(mode))
        STATUS.connect('file-loaded', self.file_loaded)
        STATUS.connect('all-homed', self.all_homed)
        STATUS.connect('not-all-homed', self.not_all_homed)
        STATUS.connect('periodic', lambda w: self.update_runtimer())
        STATUS.connect('command-stopped', lambda w: self.stop_timer())
        STATUS.connect('progress', lambda w,p,t: self.updateProgress(p,t))
        STATUS.connect('override-limits-changed', lambda w, state, data: self._check_override_limits(state, data))

    def class_patch__(self):
        self.old_fman = FM.load
        FM.load = self.load_code

    ##########################################
    # Special Functions called from QTSCREEN
    ##########################################

    # at this point:
    # the widgets are instantiated.
    # the HAL pins are built but HAL is not set ready
    def initialized__(self):
        self.init_pins()
        self.init_preferences()
        self.init_widgets()
        self.init_probe()
        self.init_utils()
        KEYBIND.add_call('Key_F12','on_keycall_F12')

    def processed_key_event__(self,receiver,event,is_pressed,key,code,shift,cntrl):
        LOG.info("processed_key_event__")
        # when typing in MDI, we don't want keybinding to call functions
        # so we catch and process the events directly.
        # We do want ESC, F1 and F2 to call keybinding functions though
        if code not in(QtCore.Qt.Key_Escape,QtCore.Qt.Key_F1 ,QtCore.Qt.Key_F2,
                    QtCore.Qt.Key_F3,QtCore.Qt.Key_F5,QtCore.Qt.Key_F5):

            # search for the top widget of whatever widget received the event
            # then check if it's one we want the keypress events to go to
            flag = False
            receiver2 = receiver
            while receiver2 is not None and not flag:
                if isinstance(receiver2, QtWidgets.QDialog):
                    flag = True
                    break
                if isinstance(receiver2, MDI_WIDGET):
                    flag = True
                    break
                if isinstance(receiver2, GCODE):
                    flag = True
                    break
                receiver2 = receiver2.parent()

            if flag:
                if isinstance(receiver2, GCODE):
                    # if in manual do our keybindings - otherwise
                    # send events to gcode widget
                    if STATUS.is_man_mode() == False:
                        if is_pressed:
                            receiver.keyPressEvent(event)
                            event.accept()
                        return True
                elif is_pressed:
                    receiver.keyPressEvent(event)
                    event.accept()
                    return True
                else:
                    event.accept()
                    return True

        if event.isAutoRepeat():return True

        # ok if we got here then try keybindings function calls
        # KEYBINDING will call functions from handler file as
        # registered by KEYBIND.add_call(KEY,FUNCTION) above
        return KEYBIND.manage_function_calls(self,event,is_pressed,key,shift,cntrl)
    
    def init_utils(self):
        from qtvcp.lib.gcode_utility.facing import Facing
        self.facing = Facing()
        #self.w.layout_facing.addWidget(self.facing)

        #from qtvcp.lib.gcode_utility.hole_circle import Hole_Circle
        #self.hole_circle = Hole_Circle()
        #self.w.layout_hole_circle.addWidget(self.hole_circle)

        # load the NgcGui widget into the utilities tab
        # then move (warp) the info tab from it to the left tab widget
        #from qtvcp.lib.qt_ngcgui.ngcgui import NgcGui
        #self.ngcgui = NgcGui()
        #self.w.layout_ngcgui.addWidget(self.ngcgui)
        #self.ngcgui.warp_info_frame(self.w.ngcGuiLeftLayout)
    
    def init_pins(self):
        # spindle control pins
        pin = QHAL.newpin("spindle-amps", QHAL.HAL_FLOAT, QHAL.HAL_IN)
        pin.value_changed.connect(self.spindle_pwr_changed)
        pin = QHAL.newpin("spindle-volts", QHAL.HAL_FLOAT, QHAL.HAL_IN)
        pin.value_changed.connect(self.spindle_pwr_changed)
        pin = QHAL.newpin("spindle-fault", QHAL.HAL_U32, QHAL.HAL_IN)
        pin.value_changed.connect(self.spindle_fault_changed)
        pin = QHAL.newpin("spindle-modbus-errors", QHAL.HAL_U32, QHAL.HAL_IN)
        pin.value_changed.connect(self.mb_errors_changed)
        QHAL.newpin("spindle-inhibit", QHAL.HAL_BIT, QHAL.HAL_OUT)
        # external offset control pins
        QHAL.newpin("eoffset-enable", QHAL.HAL_BIT, QHAL.HAL_OUT)
        QHAL.newpin("eoffset-clear", QHAL.HAL_BIT, QHAL.HAL_OUT)
        QHAL.newpin("eoffset-count", QHAL.HAL_S32, QHAL.HAL_OUT)
        pin = QHAL.newpin("eoffset-value", QHAL.HAL_FLOAT, QHAL.HAL_IN)
    
    def init_preferences(self):
        if not self.w.PREFS_:
            self.add_status("CRITICAL - no preference file found, enable preferences in screenoptions widget")
            return
        self.last_loaded_program = self.w.PREFS_.getpref('last_loaded_file', None, str,'BOOK_KEEPING')
        self.reload_tool = self.w.PREFS_.getpref('Tool to load', 0, int,'CUSTOM_FORM_ENTRIES')

    def closing_cleanup__(self):
        if not self.w.PREFS_: return
        if self.last_loaded_program is not None:
            self.w.PREFS_.putpref('last_loaded_directory', os.path.dirname(self.last_loaded_program), str, 'BOOK_KEEPING')
            self.w.PREFS_.putpref('last_loaded_file', self.last_loaded_program, str, 'BOOK_KEEPING')

    def init_widgets(self):
        self.w.filemanager.list.setAlternatingRowColors(False)
        self.w.cmb_gcode_history.addItem("No File Loaded")
        self.w.cmb_gcode_history.wheelEvent = lambda event: None
        #set up gcode list
        self.gcodes.setup_list()
    
    def init_probe(self):
        probe = INFO.get_error_safe_setting('PROBE', 'USE_PROBE', 'none').lower()
        if probe == 'versaprobe':
            LOG.info("Using Versa Probe")
            from qtvcp.widgets.versa_probe import VersaProbe
            self.probe = VersaProbe()
            self.probe.setObjectName('versaprobe')
        elif probe == 'basicprobe':
            LOG.info("Using Basic Probe")
            from qtvcp.widgets.basic_probe import BasicProbe
            self.probe = BasicProbe()
            self.probe.setObjectName('basicprobe')
        else:
            LOG.info("No valid probe widget specified")
            #self.w.btn_probe.hide()
            return
        self.w.probe_layout.addWidget(self.probe)
        self.probe.hal_init()

    ########################
    # callbacks from STATUS #
    ########################
    def spindle_pwr_changed(self, data):
        # this calculation assumes the voltage is line to neutral
        # and that the synchronous motor spindle has a power factor of 0.9
        power = self.hal['spindle-volts'] * self.hal['spindle-amps'] * 2.7 # 3 x V x I x PF
        amps = "{:1.1f}".format(self.hal['spindle-amps'])
        pwr = "{:1.1f}".format(power)
        self.w.lbl_spindle_amps.setText(amps)
        self.w.lbl_spindle_power.setText(pwr)

    def spindle_fault_changed(self, data):
        fault = hex(self.hal['spindle-fault'])
        self.w.lbl_spindle_fault.setText(fault)

    def mb_errors_changed(self, data):
        errors = self.hal['spindle-modbus-errors']
        self.w.lbl_mb_errors.setText(str(errors))

    def file_loaded(self, obj, filename):
        if os.path.basename(filename).count('.') > 1:
            self.last_loaded_program = ""
            return
        if filename is not None:
            self.add_status("Loaded file {}".format(filename))
            self.w.progressBar.setValue(0)
            self.last_loaded_program = filename
            self.w.lbl_runtime.setText("00:00:00")
        else:
            self.add_status("Filename not valid", CRITICAL)

    def updateProgress(self, p,text):
        if p <0:
            self.w.progressBar.setValue(0)
            self.w.progressBar.setFormat('PROGRESS')
        else:
            self.w.progressBar.setValue(p)
            self.w.progressBar.setFormat('{}: {}%'.format(text, p))

    def percent_loaded_changed(self, fraction):
        if fraction <0:
            self.w.progressBar.setValue(0)
            self.w.progressBar.setFormat('PROGRESS')
        else:
            self.w.progressBar.setValue(fraction)
            self.w.progressBar.setFormat('LOADING: {}%'.format(fraction))

    def percent_done_changed(self, fraction):
        self.w.progressBar.setValue(fraction)
        if fraction <0:
            self.w.progressBar.setValue(0)
            self.w.progressBar.setFormat('PROGRESS')
        else:
            self.w.progressBar.setFormat('COMPLETE: {}%'.format(fraction))

    #######################
    # callbacks from form #
    #######################
    def btn_load_file_clicked(self):
        fname = self.w.filemanager.getCurrentSelected()
        if fname[1] is True:
            self.load_code(fname[0])

    # gcode frame
    def cmb_gcode_history_clicked(self):
        if self.w.cmb_gcode_history.currentIndex() == 0: return
        filename = self.w.cmb_gcode_history.currentText()
        if filename == self.last_loaded_program:
            self.add_status("Selected program is already loaded")
        else:
            ACTION.OPEN_PROGRAM(filename)
    
    # program frame
    def btn_start_clicked(self, obj):
        if not STATUS.is_all_homed():
           self.add_status("Machine must be is homed", CRITICAL)
           return
        if not  os.path.exists(self.last_loaded_program):
            self.add_status("No program to execute", WARNING)
            return
        if not STATUS.is_auto_mode():
            self.add_status("Must be in AUTO mode to run a program", WARNING)
            return
        #if self.w.main_tab_widget.currentIndex() != 0:
        #    self.add_status("Switch view mode to MAIN", WARNING)
        #    return
        if STATUS.is_auto_running():
            self.add_status("Program is already running", WARNING)
            return
        self.run_time = 0
        self.w.lbl_runtime.setText("00:00:00")
        if self.start_line <= 1:
            LOG.info("is_auto_mode:{}, is_auto_paused: {}, is_auto_running: {} ".
                format(STATUS.is_auto_mode(), STATUS.is_auto_paused(), STATUS.is_auto_running()) 
            )
            ACTION.RUN(self.start_line)
        else:
            # instantiate run from line preset dialog
            info = '<b>Running From Line: {} <\b>'.format(self.start_line)
            mess = {'NAME':'RUNFROMLINE', 'TITLE':'Preset Dialog', 'ID':'_RUNFROMLINE', 'MESSAGE':info, 'LINE':self.start_line}
            ACTION.CALL_DIALOG(mess)
        self.add_status("Started program from line {}".format(self.start_line))
        self.timer_on = True

    def chk_run_from_line_checked(self, state):
        self.w.btn_start.setText("START\n1") if state else self.w.btn_start.setText("CYCLE\nSTART")

    def btn_reload_file_clicked(self):
        if self.last_loaded_program:
            self.w.progressBar.setValue(0)
            self.add_status("Loaded program file {}".format(self.last_loaded_program))
            ACTION.OPEN_PROGRAM(self.last_loaded_program)

    # DRO frame
    def btn_home_all_clicked(self, obj):
        if self.home_all is False:
            ACTION.SET_MACHINE_HOMING(-1)
        else:
        # instantiate dialog box
            info = "Unhome All Axes?"
            mess = {'NAME':'MESSAGE', 'ID':'_unhome_', 'MESSAGE':'UNHOME ALL', 'MORE':info, 'TYPE':'OKCANCEL'}
            ACTION.CALL_DIALOG(mess)

    def btn_home_clicked(self):
        axisnum = self.w.sender().property('joint')
        joint = INFO.get_jnum_from_axisnum(axisnum)
        if STATUS.is_joint_homed(joint) == True:
            ACTION.SET_MACHINE_UNHOMED(joint)
        else:
            ACTION.SET_MACHINE_HOMING(joint)
    
    # tool frame
    def disable_pause_buttons(self, state):
        self.w.action_pause.setEnabled(not state)
        self.w.action_step.setEnabled(not state)
        if state:
        # set external offsets to lift spindle
            self.hal['eoffset-enable'] = self.w.chk_eoffsets.isChecked()
            fval = float(self.w.lineEdit_eoffset_count.text())
            self.hal['eoffset-count'] = int(fval)
            self.hal['spindle-inhibit'] = True
        else:
            self.hal['eoffset-count'] = 0
            self.hal['eoffset-clear'] = True
            self.hal['spindle-inhibit'] = False
        # instantiate warning box
            info = "Wait for spindle at speed signal before resuming"
            mess = {'NAME':'MESSAGE', 'ICON':'WARNING', 'ID':'_wait_resume_', 'MESSAGE':'CAUTION', 'MORE':info, 'TYPE':'OK'}
            ACTION.CALL_DIALOG(mess)

    # override frame
    def slow_button_clicked(self, state):
        slider = self.w.sender().property('slider')
        current = self.w[slider].value()
        max = self.w[slider].maximum()
        if state:
            self.w.sender().setText("SLOW")
            self.w[slider].setMaximum(max / self.slow_jog_factor)
            self.w[slider].setValue(current / self.slow_jog_factor)
            self.w[slider].setPageStep(10)
        else:
            self.w.sender().setText("FAST")
            self.w[slider].setMaximum(max * self.slow_jog_factor)
            self.w[slider].setValue(current * self.slow_jog_factor)
            self.w[slider].setPageStep(100)

    def slider_maxv_changed(self, value):
        maxpc = (float(value) / INFO.MAX_LINEAR_JOG_VEL) * 100
        self.w.lbl_maxv_percent.setText("{:3.0f} %".format(maxpc))

    def slider_rapid_changed(self, value):
        rapid = (float(value) / 100) * self.factor
        self.w.lbl_max_rapid.setText("{:4.0f}".format(rapid))

    def btn_maxv_100_clicked(self):
        self.w.slider_maxv_ovr.setValue(INFO.MAX_LINEAR_JOG_VEL)

    def btn_maxv_50_clicked(self):
        self.w.slider_maxv_ovr.setValue(INFO.MAX_LINEAR_JOG_VEL / 2)

    #####################
    # general functions #
    #####################

    def load_code(self, fname):
        if fname is None: return
        filename, file_extension = os.path.splitext(fname)
        # loading ngc then HTML/PDF
        if not file_extension in (".html", '.pdf'):
            if not (INFO.program_extension_valid(fname)):
                self.add_status("Unknown or invalid filename extension {}".format(file_extension), CRITICAL)
                return
            self.w.cmb_gcode_history.addItem(fname)
            self.w.cmb_gcode_history.setCurrentIndex(self.w.cmb_gcode_history.count() - 1)
            self.w.cmb_gcode_history.setToolTip(fname)
            ACTION.OPEN_PROGRAM(fname)
            self.add_status("Loaded program file : {}".format(fname))
            #self.adjust_stacked_widgets(TAB_MAIN)
            self.w.filemanager.recordBookKeeping()
            # adjust ending to check for related HTML setup files
            fname = filename+'.html'
            if os.path.exists(fname):
                #self.w.web_view.load(QtCore.QUrl.fromLocalFile(fname))
                self.add_status("Loaded HTML file : {}".format(fname), CRITICAL)
            else:
                #self.w.web_view.setHtml(self.html)
                NOP
            # look for PDF setup files
            # load it with system program
            fname = filename+'.pdf'
            if os.path.exists(fname):
                #self.PDFView.loadView(fname)
                self.add_status("Loaded PDF file : {}".format(fname))
            else:
                #self.PDFView.loadSample('setup_tab')
                NOP
            return

        # loading HTML/PDF directly
        #if file_extension == ".html":
        #    try:
        #        self.w.web_view.load(QtCore.QUrl.fromLocalFile(fname))
        #        self.add_status("Loaded HTML file : {}".format(fname))
        #        self.w.main_tab_widget.setCurrentIndex(TAB_SETUP)
        #        self.w.stackedWidget.setCurrentIndex(0)
        #        self.w.btn_setup.setChecked(True)
        #        self.w.jogging_frame.hide()
        #    except Exception as e:
        #        print("Error loading HTML file : {}".format(e))
        #else:
        #    if os.path.exists(fname):
        #        self.PDFView.loadView(fname)
        #        self.add_status("Loaded PDF file : {}".format(fname))

    def disable_spindle_pause(self):
        self.hal['eoffset-count'] = 0
        self.hal['spindle-inhibit'] = False
        if self.w.btn_spindle_pause.isChecked():
            self.w.btn_spindle_pause.setChecked(False)
    
    # keyboard jogging from key binding calls
    # double the rate if fast is true 
    def kb_jog(self, state, joint, direction, fast = False, linear = True):
        LOG.info("kb_jog")
        if not STATUS.is_man_mode() or not STATUS.machine_is_on():
            return
        if linear:
            distance = STATUS.get_jog_increment()
            rate = STATUS.get_jograte()/60
        else:
            distance = STATUS.get_jog_increment_angular()
            rate = STATUS.get_jograte_angular()/60
        if state:
            if fast:
                rate = rate * 2
            ACTION.JOG(joint, direction, rate, distance)
        else:
            ACTION.JOG(joint, 0, 0, 0)
    
    def add_status(self, message, alertLevel = DEFAULT):
        if alertLevel==DEFAULT:
            self.set_style_default()
        elif alertLevel==WARNING:
            self.set_style_warning()
        else:
            self.set_style_critical()
        self.w.lineEdit_statusbar.setText(message)
        STATUS.emit('update-machine-log', message, 'TIME')

    def enable_auto(self, state):
        for widget in self.auto_list:
            self.w[widget].setEnabled(state)
        #if state is True:
        #    if self.w.main_tab_widget.currentIndex() != TAB_SETUP:
        #        self.w.jogging_frame.show()
        #else:
        #    if self.w.main_tab_widget.currentIndex() != TAB_PROBE:
        #        self.w.jogging_frame.hide()
        #        self.w.btn_main.setChecked(True)
        #        self.adjust_stacked_widgets(TAB_MAIN)
        #        self.w.stackedWidget.setCurrentIndex(0)
        #        self.w.stackedWidget_dro.setCurrentIndex(0)

    def enable_onoff(self, state):
        if state:
            self.add_status("Machine ON")
        else:
            self.add_status("Machine OFF")
        self.w.btn_spindle_pause.setChecked(False)
        self.hal['eoffset-count'] = 0
        #for widget in self.onoff_list:
        #    self.w[widget].setEnabled(state)
    
    def set_start_line(self, line):
        if self.w.chk_run_from_line.isChecked():
            self.start_line = line
            self.w.btn_start.setText("START\n{}".format(self.start_line))
        else:
            self.start_line = 1
    
    def update_runtimer(self):
        if self.timer_on is False or STATUS.is_auto_paused(): return
        self.time_tenths += 1
        if self.time_tenths == 10:
            self.time_tenths = 0
            self.run_time += 1
            hours, remainder = divmod(self.run_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.w.lbl_runtime.setText("{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds))
    
    def stop_timer(self):
        self.timer_on = False
        if STATUS.is_auto_mode():
            self.add_status("Run timer stopped at {}".format(self.w.lbl_runtime.text()))


    def all_homed(self, obj):
        self.home_all = True
        self.w.btn_home_all.setText("ALL HOMED")
        if self.first_turnon is True:
            self.first_turnon = False
            if self.w.chk_reload_tool.isChecked():
                command = "M61 Q{} G43".format(self.reload_tool)
                ACTION.CALL_MDI(command)
            if self.last_loaded_program is not None and self.w.chk_reload_program.isChecked():
                if os.path.isfile(self.last_loaded_program):
                    self.w.cmb_gcode_history.addItem(self.last_loaded_program)
                    self.w.cmb_gcode_history.setCurrentIndex(self.w.cmb_gcode_history.count() - 1)
                    self.w.cmb_gcode_history.setToolTip(self.last_loaded_program)
                    ACTION.OPEN_PROGRAM(self.last_loaded_program)
        ACTION.SET_MANUAL_MODE()
        self.w.manual_mode_button.setChecked(True)

    def not_all_homed(self, obj, list):
        self.home_all = False
        self.w.btn_home_all.setText("HOME ALL")
    
    def hard_limit_tripped(self, obj, tripped, list_of_tripped):
        self.add_status("Hard limits tripped", CRITICAL)
        self.w.chk_override_limits.setEnabled(tripped)
        if not tripped:
            self.w.chk_override_limits.setChecked(False)
    
    def update_rpm(self, speed):
        if self.max_spindle_rpm < int(speed) < self.min_spindle_rpm:
            if STATUS.is_spindle_on():
                #self.w.lbl_spindle_set.setProperty('in_range', False)
                #self.w.lbl_spindle_set.style().unpolish(self.w.lbl_spindle_set)
                #self.w.lbl_spindle_set.style().polish(self.w.lbl_spindle_set)
                NOP
        else:
            #self.w.lbl_spindle_set.setProperty('in_range', True)
            #self.w.lbl_spindle_set.style().unpolish(self.w.lbl_spindle_set)
            #self.w.lbl_spindle_set.style().polish(self.w.lbl_spindle_set)
            NOP
    
    def user_system_changed(self, data):
        sys = self.system_list[int(data) - 1]
        #self.w.offset_table.selectRow(int(data) + 3)
        #self.w.actionbutton_rel.setText(sys)

    def metric_mode_changed(self, mode):
        rate = (float(self.w.slider_rapid_ovr.value()) / 100)
        if mode is False:
            self.w.lbl_jog_linear.setText('INCH/<sup>MIN</sup>')
            self.factor = INFO.convert_machine_to_imperial(INFO.MAX_TRAJ_VELOCITY)
        else:
            self.w.lbl_jog_linear.setText('MM/<sup>MIN</sup>')
            self.factor = INFO.convert_machine_to_metric(INFO.MAX_TRAJ_VELOCITY)
        self.w.lbl_max_rapid.setText("{:4.0f}".format(rate * self.factor))

    # keep check button in synch of external changes
    def _check_override_limits(self,state,data):
        if 0 in data:
            self.w.chk_override_limits.setChecked(False)
        else:
            self.w.chk_override_limits.setChecked(True)

    def set_button_response_state(self, state):
        for i in (self.button_response_list):
            self.w[i].setEnabled(not state)

    # change Status bar text color
    def set_style_default(self):
        self.w.lineEdit_statusbar.setStyleSheet("background-color: rgb(252, 252, 252);color: rgb(0,0,0)")  #default white
    
    def set_style_warning(self):
        self.w.lineEdit_statusbar.setStyleSheet("background-color: rgb(242, 246, 103);color: rgb(0,0,0)")  #yelow
    
    def set_style_critical(self):
        self.w.lineEdit_statusbar.setStyleSheet("background-color: rgb(255, 144, 0);color: rgb(0,0,0)")   #orange

    #####################
    # KEY BINDING CALLS #
    #####################

    # Machine control
    def on_keycall_ESTOP(self,event,state,shift,cntrl):
        LOG.info("on_keycall_ESTOP")
        if state:
            ACTION.SET_ESTOP_STATE(STATUS.estop_is_clear())
    
    def on_keycall_POWER(self,event,state,shift,cntrl):
        LOG.info("on_keycall_POWER")
        if state:
            ACTION.SET_MACHINE_STATE(not STATUS.machine_is_on())
    
    def on_keycall_ABORT(self,event,state,shift,cntrl):
        LOG.info("on_keycall_ABORT")
        if state:
            if STATUS.stat.interp_state == linuxcnc.INTERP_IDLE:
                self.w.close()
            else:
                self.cmnd.abort()
    def on_keycall_HOME(self,event,state,shift,cntrl):
        LOG.info("on_keycall_HOME")
        if state:
            if STATUS.is_all_homed():
                ACTION.SET_MACHINE_UNHOMED(-1)
            else:
                ACTION.SET_MACHINE_HOMING(-1)    

    def on_keycall_F12(self,event,state,shift,cntrl):
        LOG.info("on_keycall_F12")
        self.w.labelStatus.setText("on_keycall_F12")
        if state:
            STYLEEDITOR.load_dialog()

    def on_keycall_pause(self,event,state,shift,cntrl):
        if state and STATUS.is_auto_mode() and self.use_keyboard():
            ACTION.PAUSE()
    
    # Linear Jogging
    def on_keycall_XPOS(self,event,state,shift,cntrl):
        self.kb_jog(state, 0, 1, shift)

    def on_keycall_XNEG(self,event,state,shift,cntrl):
        self.kb_jog(state, 0, -1, shift)

    def on_keycall_YPOS(self,event,state,shift,cntrl):
        self.kb_jog(state, 1, 1, shift)

    def on_keycall_YNEG(self,event,state,shift,cntrl):
        self.kb_jog(state, 1, -1, shift)

    def on_keycall_ZPOS(self,event,state,shift,cntrl):
        self.kb_jog(state, 2, 1, shift)

    def on_keycall_ZNEG(self,event,state,shift,cntrl):
        self.kb_jog(state, 2, -1, shift)

    def on_keycall_APOS(self,event,state,shift,cntrl):
        pass
        #self.kb_jog(state, 3, 1, shift, False)

    def on_keycall_ANEG(self,event,state,shift,cntrl):
        pass
        #self.kb_jog(state, 3, -1, shift, linear=False)

    ###########################
    # **** closing event **** #
    ###########################

    ##############################
    # required class boiler code #
    ##############################

    def __getitem__(self, item):
        return getattr(self, item)
    def __setitem__(self, item, value):
        return setattr(self, item, value)

################################
# required handler boiler code #
################################

def get_handlers(halcomp,widgets,paths):
    LOG.info("get_handlers") 
    return [HandlerClass(halcomp,widgets,paths)]

