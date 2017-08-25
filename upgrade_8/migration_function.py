# -*- coding: utf-8 -*-
import os
import signal
import time
import traceback

from subprocess import call, Popen
from datetime import datetime

from migration_import import erppeek, psutil

from secret_configuration import (
    ODOO_FOLDER_BACKUP, ODOO_FOLDER_NORMAL, ODOO_FOLDER_UPGRADE,
    ODOO_LOCAL_URL,
    #    ODOO_EXTERNAL_DATABASE, ODOO_EXTERNAL_URL,
    ODOO_USER, ODOO_PASSWORD, USE_SUDO)

TEMPORARY_FOLDER = '/tmp/'
TEMPORARY_FILE_DB_LIST = '/tmp/xx_database_list'

ODOO_UPDATE_SCRIPT = "../bin/start_openerp --stop-after-init"\
    " -u {module_list} -d {database} --log-level {log_level}"


ODOO_RUN_SCRIPT = "../bin/start_openerp --log-level {log_level}"


def _log(text, error=False):
    try:
        res = '%s - %s' % (
            datetime.today().strftime("%d-%m-%y - %H:%M:%S"), text)
        print res
        if error:
            print error
            traceback.print_stack()
    except:
        pass


def _generate_command(command, user):
    if not USE_SUDO:
        return command
    elif not user:
        return 'sudo %s' % command
    else:
        return 'sudo su %s -c "%s"' % (user, command)


def _bash_execute(command, user=False, log=True):
    full_command = _generate_command(command, user)
    if log:
        _log("CALLING (Sync) %s" % full_command)
    try:
        call(full_command, shell=True)
    except Exception as e:
        _log("ERROR during the execution", e)
        return False
    return True


def _bash_subprocess(command, user=False, log=True):
    full_command = _generate_command(command, user)
    if log:
        _log("CALLING (async) %s" % full_command)
    try:
        res = Popen(full_command, shell=True)
    except Exception as e:
        _log("ERROR during the execution", e)
        return False
    return res


def manage_odoo_process(active=False):
    _log("%s Odoo Process" % ('Start' if active else 'Stop'))
    if active:
        _bash_execute("service odoo start")
    else:
        _bash_execute("service odoo stop")


def set_upgrade_mode(upgrade_mode):
    _log("Set Upgrade mode to %s" % upgrade_mode)
    if upgrade_mode and not os.path.isdir(ODOO_FOLDER_BACKUP):
        os.rename(ODOO_FOLDER_NORMAL, ODOO_FOLDER_BACKUP)
        os.rename(ODOO_FOLDER_UPGRADE, ODOO_FOLDER_NORMAL)
        os.mkdir(ODOO_FOLDER_UPGRADE)
    elif not upgrade_mode and os.path.isdir(ODOO_FOLDER_BACKUP):
        os.rmdir(ODOO_FOLDER_UPGRADE)
        os.rename(ODOO_FOLDER_NORMAL, ODOO_FOLDER_UPGRADE)
        os.rename(ODOO_FOLDER_BACKUP, ODOO_FOLDER_NORMAL)


def execute_sql_file(database, step, step_name):
    sql_file = '%d_before_%s.sql' % (step, step_name)
    if os.path.exists(sql_file):
        return _bash_execute(
            "psql -f %s %s -o %szz_%s__output_%s" % (
                sql_file, database, TEMPORARY_FOLDER, database, sql_file),
            user='postgres')


def create_new_database(target_database, step, step_name):
    _bash_execute(
        "psql -l -o %s" % TEMPORARY_FILE_DB_LIST, user='postgres', log=False)
    file_database_list = open(TEMPORARY_FILE_DB_LIST, 'r')
    content = ''.join(file_database_list.readlines())
    if step == 1:
        # found a name for the database to create
        found = True
        i = 1
        template_database = target_database
        while found:
            new_database = '%s_%s_current' % (target_database, str(i).zfill(3))
            found = ' %s ' % new_database in content
            i += 1

    else:
        template_database = '%s___%d_%s' % (target_database, step, step_name)
        new_database = '%s_current' % (target_database)
        if new_database in content:
            # Drop database
            _bash_execute("dropdb %s" % (new_database), user='postgres')

    _bash_execute(
        "createdb %s --template %s --owner odoo" % (
            new_database, template_database), user='postgres')

    _bash_execute("rm %s" % TEMPORARY_FILE_DB_LIST, log=False)
    return new_database


def backup_database(database, step, step_name):
    # TODO FIXME, disabled backup for the time being
    return
    backup = '%s___%d_%s' % (database.replace('_current', ''), step, step_name)
    # Search for previous backup
    _bash_execute(
        "psql -l -o %s" % TEMPORARY_FILE_DB_LIST, user='postgres', log=False)
    file_database_list = open(TEMPORARY_FILE_DB_LIST, 'r')
    content = file_database_list.readlines()
    found = ' %s ' % backup in ''.join(content)
    if found:
        # Drop previous backup
        _bash_execute("dropdb %s" % backup, user='postgres')
    # Backup Database
    _bash_execute(
        "createdb %s --template %s --owner odoo" % (
            backup, database), user='postgres')
    _bash_execute("rm %s" % TEMPORARY_FILE_DB_LIST, log=False)


def update_instance(database, module_list, log_level):
    _bash_execute(
        ODOO_UPDATE_SCRIPT.format(
            database=database, module_list=module_list, log_level=log_level),
        user='odoo')


def run_instance(log_level):
    res = _bash_subprocess(
        ODOO_RUN_SCRIPT.format(log_level=log_level), user='odoo')
    time.sleep(5)
    return res


def kill_process(process):
    parent = psutil.Process(process.pid)
    children_pids = [x.pid for x in parent.children(recursive=True)]
    pids = [process.pid] + children_pids
    _log("KILL Process(es) #%s" % (', '.join([str(pid) for pid in pids])))
    for pid in pids:
        _bash_execute("kill -9 %d" % pid)
    time.sleep(5)


def _connect_instance(url, database, login, password):
    try:
        openerp = erppeek.Client(url)
    except Exception as e:
        _log("ERROR : Connection to odoo instance '%s' failed" % url, e)
        return False
    try:
        openerp.login(
            login, password=password, database=database)
    except Exception as e:
        _log("ERROR : Authentication failed on %s with %s login" % (
            url, login), e)
        return False
    return openerp


def install_modules(database, module_list):
    # Update module list
    openerp = _connect_instance(
        ODOO_LOCAL_URL, database, ODOO_USER, ODOO_PASSWORD)
    if not openerp:
        _log("FATAL : install process aborted")
        return
    _log("Update modules list...")
    openerp.IrModuleModule.update_list()

    # Install each module
    for module_name in module_list:
        openerp = _connect_instance(
            ODOO_LOCAL_URL, database, ODOO_USER, ODOO_PASSWORD)
        if not openerp:
            _log("FATAL : install process aborted")
            return
        modules = openerp.IrModuleModule.browse([('name', '=', module_name)])
        if len(modules) == 0:
            _log("ERROR : Module not found %s" % module_name)
        else:
            module = modules[0]
            if modules[0].state in ['uninstalled', 'to install']:
                _log("Installing... %s" % module.name)
                try:
                    openerp.IrModuleModule.button_immediate_install(
                        [module.id])
                except Exception as e:
                    _log("ERROR during '%s' installation" % module_name, e)
            else:
                _log("WARNING : '%s' module in '%s' state" % (
                    module.name, module.state))


def uninstall_modules(database, module_list):
    # Uninstall each module
    for module_name in module_list:
        openerp = _connect_instance(
            ODOO_LOCAL_URL, database, ODOO_USER, ODOO_PASSWORD)
        if not openerp:
            _log("FATAL : uninstall process aborted")
            return
        modules = openerp.IrModuleModule.browse([('name', '=', module_name)])
        if len(modules) == 0:
            _log("ERROR : Module not found %s" % module_name)
        else:
            module = modules[0]
            if modules[0].state not in ['uninstalled']:
                _log("Uninstalling... %s" % module.name)
                try:
                    openerp.IrModuleModule.module_uninstall([module.id])
                except Exception as e:
                    _log("ERROR during '%s' uninstallation" % module_name, e)
            else:
                _log("WARNING : '%s' module in '%s' state" % (
                    module.name, module.state))
