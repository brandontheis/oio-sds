import sys
import glob
import grp
import errno
import pwd
from logging.handlers import SysLogHandler
import logging

import eventlet
import eventlet.semaphore
from eventlet.green import socket, threading


logging.thread = eventlet.green.thread
logging.threading = eventlet.green.threading
logging._lock = logging.threading.RLock()

from optparse import OptionParser
from ConfigParser import SafeConfigParser

import os
from gunicorn.app.base import BaseApplication


class Application(BaseApplication):
    access_log_fmt = '%(h)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)s'

    def __init__(self, app, conf, logger_class=None):
        self.conf = conf
        self.application = app
        self.logger_class = logger_class
        super(Application, self).__init__()

    def load_config(self):
        bind = '%s:%s' % (self.conf.get('bind_addr', '127.0.0.1'),
                          self.conf.get('bind_port', '8000'))
        self.cfg.set('bind', bind)
        self.cfg.set('backlog', self.conf.get('backlog', 2048))
        self.cfg.set('workers', self.conf.get('workers', 2))
        self.cfg.set('worker_class', 'eventlet')
        self.cfg.set('worker_connections', self.conf.get(
            'worker_connections', 1000))
        self.cfg.set('syslog_prefix', self.conf.get('syslog_prefix', ''))
        self.cfg.set('syslog_addr', self.conf.get('log_address', '/dev/log'))
        self.cfg.set('accesslog', '-')
        self.cfg.set('access_log_format', self.conf.get('access_log_format',
                                                        self.access_log_fmt))
        if self.logger_class:
            self.cfg.set('logger_class', self.logger_class)


    def load(self):
        return self.application


class NullLogger(object):
    def write(self, *args):
        pass


class StreamToLogger(object):
    def __init__(self, logger, log_type='STDOUT'):
        self.logger = logger
        self.log_type = log_type

    def write(self, value):
        value = value.strip()
        if value:
            self.logger.error('%s : %s', self.log_type, value)

    def writelines(self, values):
        self.logger.error('%s : %s', self.log_type, '#012'.join(values))

    def close(self):
        pass

    def flush(self):
        pass


def drop_privileges(user):
    if os.geteuid() == 0:
        groups = [g.gr_gid for g in grp.getgrall() if user in g.gr_mem]
        os.setgroups(groups)
    user_entry = pwd.getpwnam(user)
    os.setgid(user_entry[3])
    os.setuid(user_entry[2])
    os.environ['HOME'] = user_entry[5]
    try:
        os.setsid()
    except OSError:
        pass
    os.chdir('/')
    os.umask(0o22)


def redirect_stdio(logger):
    """
    Close stdio, redirect stdout and stderr.

    :param logger:
    """
    stdio_fd = [sys.stdin, sys.stdout, sys.stderr]
    console_fds = [h.stream.fileno() for _, h in getattr(
        get_logger, 'console_handler4logger', {}).items()]
    stdio_fd = [fd for fd in stdio_fd if fd.fileno() not in console_fds]

    with open(os.devnull, 'r+b') as nullfile:
        for fd in stdio_fd:
            try:
                fd.flush()
            except IOError:
                pass

            try:
                os.dup2(nullfile.fileno(), fd.fileno())
            except OSError:
                pass

    sys.stdout = StreamToLogger(logger)
    sys.stderr = StreamToLogger(logger, 'STDERR')


def get_logger(conf, name=None, verbose=False, fmt="%(message)s"):
    if not conf:
        conf = {}
    if name is None:
        name = 'oio'
    logger = logging.getLogger(name)
    logger.propagate = False

    syslog_prefix = conf.get('syslog_prefix', '')

    formatter = logging.Formatter(fmt=fmt)
    if syslog_prefix:
        fmt = '%s: %s' % (syslog_prefix, fmt)

    syslog_formatter = logging.Formatter(fmt=fmt)

    if not hasattr(get_logger, 'handler4logger'):
        get_logger.handler4logger = {}
    if logger in get_logger.handler4logger:
        logger.removeHandler(get_logger.handler4logger[logger])

    facility = getattr(SysLogHandler, conf.get('log_facility', 'LOG_LOCAL0'),
                       SysLogHandler.LOG_LOCAL0)

    log_address = conf.get('log_address', '/dev/log')
    try:
        handler = SysLogHandler(address=log_address, facility=facility)
    except socket.error as e:
        if e.errno not in [errno.ENOTSOCK, errno.ENOENT]:
            raise e
        handler = SysLogHandler(facility=facility)

    handler.setFormatter(syslog_formatter)
    logger.addHandler(handler)
    get_logger.handler4logger[logger] = handler

    if verbose or hasattr(get_logger, 'console_handler4logger'):
        if not hasattr(get_logger, 'console_handler4logger'):
            get_logger.console_handler4logger = {}
        if logger in get_logger.console_handler4logger:
            logger.removeHandler(get_logger.console_handler4logger[logger])

        console_handler = logging.StreamHandler(sys.__stderr__)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        get_logger.console_handler4logger[logger] = console_handler

    logging_level = getattr(logging, conf.get('log_level', 'INFO').upper(),
                            logging.INFO)
    logger.setLevel(logging_level)

    return logger


def parse_options(parser=None):
    if parser is None:
        parser = OptionParser(usage='%prog CONFIG [options]')
    parser.add_option('-v', '--verbose', default=False,
                      action='store_true', help='verbose output')

    options, args = parser.parse_args(args=None)

    if not args:
        parser.print_usage()
        print("Error: missing argument config path")
        sys.exit(1)
    config = os.path.abspath(args.pop(0))
    if not os.path.exists(config):
        parser.print_usage()
        print("Error: unable to locate %s" % config)
        sys.exit(1)

    options = vars(options)

    return config, options


def read_conf(conf_path, section_name=None, defaults=None):
    if defaults is None:
        defaults = {}
    c = SafeConfigParser(defaults)
    success = c.read(conf_path)
    if not success:
        print("Unable to read config from %s" % conf_path)
        sys.exit(1)
    if section_name:
        if c.has_section(section_name):
            conf = dict(c.items(section_name))
        else:
            print('Unable to find section %s in config %s' % (section_name,
                                                              conf_path))
            sys.exit(1)
    else:
        conf = {}
        for s in c.sections():
            conf.update({s: dict(c.items(s))})
    return conf


TIMESTAMP_FORMAT = "%016.05f"


class Timestamp(object):
    def __init__(self, timestamp):
        self.timestamp = float(timestamp)

    def __repr__(self):
        return self.normal

    def __float__(self):
        return self.timestamp

    def __int__(self):
        return int(self.timestamp)

    def __nonzero__(self):
        return bool(self.timestamp)

    @property
    def normal(self):
        return TIMESTAMP_FORMAT % self.timestamp

    def __eq__(self, other):
        if not isinstance(other, Timestamp):
            other = Timestamp(other)
        return self.timestamp == other.timestamp

    def __ne__(self, other):
        if not isinstance(other, Timestamp):
            other = Timestamp(other)
        return self.timestamp != other.timestamp

    def __cmp__(self, other):
        if not isinstance(other, Timestamp):
            other = Timestamp(other)
        return cmp(self.timestamp, other.timestamp)


def int_value(value, default):
    if value in (None, 'None'):
        return default
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise
    return value


class InvalidServiceConfigError(ValueError):
    def __str__(self):
        return "namespace missing from service conf"


def validate_service_conf(conf):
    ns = conf.get('namespace')
    if not ns:
        raise InvalidServiceConfigError()


def load_namespace_conf(namespace):
    def places():
        yield '/etc/oio/sds.conf'
        for f in glob.glob('/etc/oio/sds/conf.d/*'):
            yield f
        yield os.path.expanduser('~/.oio/sds.conf')

    c = SafeConfigParser({})
    success = c.read(places())
    if not success:
        print('Unable to read namespace config')
        sys.exit(1)
    if c.has_section(namespace):
        conf = dict(c.items(namespace))
    else:
        print('Unable to find [%s] section config' % namespace)
        sys.exit(1)
    for k in ['zookeeper', 'conscience', 'proxy', 'event-agent']:
        v = conf.get(k)
        if not v:
            print("Missing field '%s' in namespace config" % k)
            sys.exit(1)
    return conf

