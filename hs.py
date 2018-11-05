import multiprocessing
import SocketServer
import threading
import cStringIO
import logging
import inspect
import select
import socket
import string
import random
import struct
import signal
import types
import time
import cmd
import ssl
import sys
import os
import re

def p32(d):
    return struct.pack('<I', d)

def u32(d):
    return struct.unpack('<I', d)[0]

class Fordwarder():
    def __init__(self, client_socket, appserver_socket):
        self.__client_socket = client_socket
        self.__server_socket = appserver_socket
    
    def zloop(self):
        global timeout
        global connection_handler_logger

        READ_SIZE = 4096

        input_data = ''
        output_data = ''

        while True:
            time.sleep(timeout)
            try:
                readable, writeable, exceptions = select.select((self.__client_socket, self.__server_socket), [], [])
                for s in readable:
                    d = s.recv(READ_SIZE)
                    if len(d) == 0:
                        connection_handler_logger.debug('Connection closed')
                        return None
                    if (s == self.__client_socket):
                        input_data += d
                    elif (s == self.__server_socket):
                        output_data += d

                if (output_data != ''):
                    self.__client_socket.send( output_data )
                    output_data = ''
                elif (input_data != ''):
                    self.__server_socket.send( input_data )
                    input_data = ''
            except socket.error:
                break
            except Exception as e:
                connection_handler_logger.critical(e)
                break
        connection_handler_logger.debug('Connection closed')
        return None
        
    def loop(self, conn_id):
        global timeout
        global connection_handler_logger
        READ_SIZE = 4096

        input_data = ''
        output_data = ''
        '''buffer 32bytes past data'''
        inbuf = ''
        outbuf = ''
        log_data = ''

        while True:
            time.sleep(timeout)
            try:
                readable, writeable, exceptions = select.select((self.__client_socket, self.__server_socket), [], [])
                for s in readable:
                    d = s.recv(READ_SIZE)
                    if len(d) == 0:
                        connection_handler_logger.debug('Connection closed')
                        return log_data
                    if (s == self.__client_socket):
                        input_data += d
                    elif (s == self.__server_socket):
                        output_data += d

                if (output_data != ''):
                    outbuf = outbuf[-32:]
                    log_data += 'o:' + p32(len(output_data)) + output_data
                    t = output_callback(output_data, outbuf, conn_id)
                    self.__client_socket.send(t)
                    outbuf += t
                    output_data = ''
                elif (input_data != ''):
                    inbuf = inbuf[-32:]
                    log_data += 'i:' + p32(len(input_data)) + input_data
                    t = input_callback(input_data, inbuf, conn_id)
                    self.__server_socket.send(t)
                    inbuf += t
                    input_data = ''
            except socket.error:
                break
            except Exception as e:
                connection_handler_logger.critical(e)
                break
        connection_handler_logger.debug('Connection closed')
        return log_data

class TCPHandler(SocketServer.BaseRequestHandler):
    def setup(self):
        global conn_id

        thread_lock.acquire()
        self.__conn_id = conn_id
        conn_id += 1
        thread_lock.release()

        self.__log_data = None
            
    def handle(self):
        global safemode
        global connection_handler_logger
        
        connection_handler_logger.debug('Handling new connection')
        #connect to APP_SERVER
        self.__server_socket = socket.socket()
        try:
            self.__server_socket.connect( (APP_SERVER, PORT) )
        except:
            connection_handler_logger.critical('Error connecting to APP_SERVER')
            return None
        fordwarder = Fordwarder(self.request, self.__server_socket)
        if safemode:
            self.__log_data = fordwarder.zloop()
        else:
            self.__log_data = fordwarder.loop(self.__conn_id)

        
    def finish(self):
        global pool

        self.__server_socket.close()
        if self.__log_data:
            pool.apply_async(write_log, (self.__conn_id, self.__log_data, self.request.getpeername()[0]))

'''
Samelessly taken from http://kmkeen.com/socketserver/2009-02-07-07-52-15.html
'''
class TCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass):
        SocketServer.TCPServer.__init__(self, server_address, RequestHandlerClass)

class Abort(Exception):
    def __str__(self):
        return '[!] RULE ABORTED !!'

def input_callback(data, inbuf, conn_id):
    global input_rule
    global connection_handler_logger

    for f in input_rule:
        try:
            data = f(data, inbuf, conn_id)
        except Abort as e:
            raise e
        except Exception as e:
            connection_handler_logger.error(':input_callback:%s:%s' % (f.func_name, e))
    return data

def output_callback(data, outbuf, conn_id):
    global connection_handler_logger

    for f in output_rule:
        try:
            data = f(data, outbuf, conn_id)
        except Abort as e:
            raise e
        except:
            connection_handler_logger.error(':input_callback:%s:%s' % (f.func_name, e))
    return data

def reload_rule():
    global output_rule_file
    global input_rule_file
    global output_rule
    global input_rule
    global rule_logger

    def load_rule_file(fname):
        l = []

        try:
            f = open(fname, 'r')
            d = f.read()
        except:
            rule_logger.error('Error openning rule file')
            return None
        
        try:
            c = compile(d, fname, 'exec')
        except Exception as e:
            rule_logger.error(e)
            return None

        for e in c.co_consts:
            if type(e) == types.CodeType:
                l.append(types.FunctionType(e, globals()))
        return l

    l = load_rule_file(input_rule_file)
    rule_logger.debug('input_rule' + repr(l) )
    if l != None:
        input_rule = l
    l = load_rule_file(output_rule_file)
    rule_logger.debug('output_rule' + repr(l) )
    if l != None:
        output_rule = l

def set_timeout(arg):
    global timeout
    global command_logger

    try:
        timeout = float(arg) % 10.0
        command_logger.info('set timeout = %f' % timeout)
    except:
        command_logger.error('Can not parse timeout: %s' % arg)
        
def set_thread_interval(arg):
    global thread_interval
    
    try:
        thread_interval = int(arg)
        command_logger.info('set thread_interval = %d' % thread_interval)
        sys.setcheckinterval(thread_interval)
    except:
        command_logger.error('Can not parse thread_interval: %s' % arg)

def isvalidip(ip):
    try:
        socket.inet_aton(ip)
        return 1
    except socket.error:
        return 0

def set_appserver(ip):
    global APP_SERVER
    global command_logger

    if isvalidip(ip):
        APP_SERVER = ip
    else:
        command_logger.error('Invalid ip address')

def options():
    print 'thread_interval', thread_interval
    print 'conn_id', conn_id
    print 'log_id', log_id
    print 'timeout', timeout
    print 'appserver', APP_SERVER
    print 'safemode', safemode

def log_helper(arg):
    global log_id
    global command_logger

    r = [] #result log data
    t = [] #parse_arg list
    f = '' #input or ouput
    f2 = '' #raw mode or repr mode

    arg = arg.strip().split(' ')
    arg = filter(bool, arg)
    if len(arg) != 0:
        for e in arg:
            try:
                    t.append(int(e))
            except:
                if e == 'o' or e == 'i':
                    f = e
                elif e == 'r':
                    f2 = e
                else:
                    command_logger.error('Argument error')
                    return None

    if len(t) <= 1:
        try:
            idx = t[0]
        except:
            idx = log_id
        try:
            r = [get_log(idx)]
        except Exception as e:
            command_logger.error(e)
            return None
    elif len(t) == 2:
        start = t[0]
        end = t[1]

        try:
            r = slice_log(start, end)
        except Exception as e:
            command_logger.error(e)
            return None
    else:
        command_logger.error('Argument error')
        return None

    for e in r:
        if e != None:
            (i, o) = e
            
            if f == 'i':
                if f2:
                    for j in xrange(len(i)):
                        print i[j]
                else:
                    for j in xrange(len(i)):
                        print repr( i[j] )

            elif f == 'o':
                if f2:
                    for j in xrange(len(o)):
                        print o[j],
                else:
                    for j in xrange(len(o)):
                        print repr( o[j] )
            else:
                length = len(i) if len(i) > len(o) else len(o)
                if f2:
                    for j in xrange(length):
                        try:
                            print i[j] 
                            print o[j]
                        except:
                            pass
                else:
                    for j in xrange(length):
                        try:
                            print repr( i[j] )
                            print repr( o[j] )
                        except:
                            pass

def get_log(log_id):
    global command_logger
    i = []
    o = []

    try:
        with open(str(log_id), 'rb') as f:
            conn_data = f.read()
        command_logger.debug(':get_log:reading log file done')
    except:
        command_logger.error('Cannot open log file %d' % log_id)
        return None
    conn_data = cStringIO.StringIO(conn_data)
    d_type = conn_data.read(2)
    while d_type:
        length = u32(conn_data.read(4))
        data = conn_data.read(length)
        if d_type == 'i:':
            i.append(data)
        else:
            o.append(data)
        d_type = conn_data.read(2)
    return (i, o)

def slice_log(start, end):
    r = []
    i = []
    o = []
    
    for i in xrange(start, end):
        r.append(get_log(i))
    return r

def set_safemode():
    global safemode

    safemode ^= 1

def write_log(conn_id, d, client_ip):
    global log_lock

    
    try:
        with open(str(conn_id + '_' + client_ip + '.l'), 'ab') as f:
            f.write(d)
    except Exception as e:
        command_logger.error(e)
        return

    log_lock.acquire()
    log_id += 1
    log_lock.release()

def set_logger_stream(p):
    global W
    global formatter
    global stdout_stream_handler
    global current_stream_handler
   
    p = p.strip()
    if not p:
        new_stream_handler = stdout_stream_handler
    else:
        try:
            f = open(p, 'wb')
        except:
            command_logger.error('Cannot open %s' % p)
            return None
        new_stream_handler = logging.StreamHandler(stream = f)
        new_stream_handler.setFormatter(formatter)
    W.removeHandler(current_stream_handler)
    W.addHandler(new_stream_handler)
    current_stream_handler = new_stream_handler

def init_worker():
    signal.signal(signal.SIGINT, signal.SIG_IGN)

def shutdown():
    global running
    global server
    global pool

    running = 0
    server.server_close()
    pool.terminate()
    pool.join()

class my_cmd(cmd.Cmd):
    def keyboard_interrupt(self):
        self.do_exit()

    def do_exit(self, arg):
        shutdown()
        return True

    def do_appserver(self, arg):
        set_appserver(arg)

    def do_interval(self, arg):
        set_thread_interval(arg)

    def do_reload(self, arg):
        reload_rule()

    def do_timeout(self, arg):  
        set_timeout(arg)

    def do_cls(self, arg):
        os.system('clear')

    def do_options(self, arg):
        options()

    def do_log(self, arg):
        log_helper(arg)


    def do_safe(self, arg):
        set_safemode()
        
    def do_critical(self, arg):
        global loggers

        for e in loggers:
            e.setLevel(logging.CRITICAL)

    def do_error(self, arg):
        global loggers

        for e in loggers:
            e.setLevel(logging.ERROR)

    def do_warning(self, arg):
        global loggers

        for e in loggers:
            e.setLevel(logging.WARNING)

    def do_info(self, arg):
        global loggers

        for e in loggers:
            e.setLevel(logging.INFO)

    def do_debug(self, arg):
        global loggers

        for e in loggers:
            e.setLevel(logging.DEBUG)

    def do_out(self, arg):
        set_logger_stream(arg)
        pass

def cmd_loop():
    c = my_cmd()
    c.prompt = '> '
    try:
        c.cmdloop()
    except KeyboardInterrupt:
        return None

if __name__ == '__main__':
    '''locks'''
    screen_lock = threading.Lock()
    thread_lock = threading.Lock()
    log_lock    = multiprocessing.Lock()

    '''config vars'''
    timeout = 0.01
    thread_interval = 10
    '''
    https://stackoverflow.com/questions/43771575/accurate-sleep-delay-within-python-while-loop
    '''
    sys.setcheckinterval(thread_interval)

    '''challenge name'''
    NAME = sys.argv[1]
    '''ip of appserver'''
    APP_SERVER = sys.argv[2]
    '''challenge port'''
    PORT = int( sys.argv[3] )
    '''interface'''
    IF = sys.argv[4]
    '''LISTEN PORT'''
    LPORT = int( sys.argv[5] )
    
    '''files'''
    input_rule_file = NAME + '_in_rule.py'
    output_rule_file = NAME + '_out_rule.py'

    '''change current working directory'''
    if not os.path.isdir(NAME):
        os.makedirs(NAME)
    os.chdir(NAME)

    if not os.path.exists(input_rule_file):
        f = open(input_rule_file, 'a')
        f.close()
    if not os.path.exists(output_rule_file):
        f = open(output_rule_file, 'a')
        f.close()

    '''log worker'''
    pool = multiprocessing.Pool(initializer = init_worker, processes = 2)
    
    '''loggers'''
    stdout_stream_handler     = logging.StreamHandler()
    current_stream_handler    = stdout_stream_handler
    formatter                 = logging.Formatter('%(levelname)s:%(name)s:%(message)s')
    stdout_stream_handler.setFormatter  (formatter)
    stdout_stream_handler.setLevel      (logging.DEBUG)
    W                         = logging.getLogger(NAME + '===')
    rule_logger               = logging.getLogger(NAME + '_rule_logger')
    command_logger            = logging.getLogger(NAME + '_command_logger')
    connection_handler_logger = logging.getLogger(NAME + '_connection_handler')
    W.addHandler                        (stdout_stream_handler)
    rule_logger.addHandler              (stdout_stream_handler)
    command_logger.addHandler           (stdout_stream_handler)
    connection_handler_logger.addHandler(stdout_stream_handler)
    loggers = [connection_handler_logger, command_logger, rule_logger]

    '''default logging level'''
    for e in loggers:
        e.setLevel(logging.ERROR)

    '''other globals'''
    conn_per_file   = 2
    input_rule      = []
    output_rule     = []
    safemode        = 0

    '''set conn_id | log_id'''
    conn_id = 0
    log_id  = 0

    n_files = os.listdir('./')
    for n_name in n_files:
        if n_name.endswith('.l'):
            conn_id += 1
            log_id  += 1

    running = 1

    cmd_thread = threading.Thread(target = cmd_loop)
    cmd_thread.start()
    reload_rule()
    server = TCPServer((IF, LPORT), TCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        shutdown()
    except Exception as e:
        command_logger.error(e)
