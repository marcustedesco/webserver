#!/usr/bin/python
#
# The purpose of this class is to drive unit tests against a server that
# handles requests for system statistics.  Unit tests will cover a number
# of areas, described as the following suites of tests:
#
#   1.  Correctness for good requests
#   2.  Correctness for expectable bad requests
#   3.  Malicious request handling
#
#

import sys

import unittest, httplib, json, os, socket, getopt, \
       subprocess, signal, traceback, time, atexit, inspect, math, struct
from fractions import Fraction as F

# add directory in which script is located to python path
# we import server_check from there
script_dir = "/".join(__file__.split("/")[:-1])
if script_dir == "":
    script_dir = "."
if script_dir not in sys.path:
    sys.path.append(script_dir)

import server_check

def usage():
    print """
    Usage: python server_unit_test.py -s server [-h, -t testname, -o outfile]
        -h              Show help 
        -s server       File path to the server executable
        -t testname     Run a test by itself, its name given as testname
        -l              List available tests
        -o outputfile   Send output from the server to an output file
          """

def handle_exception(type, exc, tb):
    """Install a default exception handler.
    If there is an exception thrown at any time in the script,
    report that the test failed, close the server and exit.
    """
    print "\n>>> FAIL: ", type, "'", exc, "'\n"
    print type.__doc__ + "\n"
    traceback.print_tb(tb)
    
#Install the default exception handler
sys.excepthook = handle_exception



##############################################################################
## Class: Doc_Print_Test_Case
## Extending the unittest.TestCase class for a better print of the __doc__ 
## type of each test method.
##
#
# TBD: investigate if this method was only used in Python 2.4 and isn't
# already part of TestCase in unittest in Python 2.6
#
##############################################################################

class Doc_Print_Test_Case(unittest.TestCase):
    
    def __init__(self, methodName='runTest'):
        """
        Overriding the super-class __init__ because it uses an internal
        attribute for the test method doc that is not inherited.
        """
        try:
            self._testMethodName = methodName
            testMethod = getattr(self, methodName)
            self._testMethodDoc = testMethod.__doc__
        except AttributeError:
            raise ValueError, "no such test method in %s: %s" % \
                  (self.__class__, methodName)

    def shortDescription(self):
        """
        Returns the __doc__ of the test method, instead of unittest.TestCase's
        standard action of returning the first line of the test method.  This
        will allow for more verbose testing with each method.
        """
        return self._testMethodDoc







##############################################################################
## Class: Single_Conn_Protocol_Case
## test cases that ensure HTTP/1.0 connections close automatically,
## and HTTP/1.1 connections have persistent connections.
##############################################################################

class Single_Conn_Protocol_Case ( Doc_Print_Test_Case ):
    """
    Test case for a single connection, checking various points of protocol
    usage that ensures the servers to be HTTP 1.0 and 1.1 compliant.
    Each case should be handled without the server crashing.
    """

    def __init__(self, testname, hostname, port):
        """
        Prepare the test case for creating connections.
        """
        super(Single_Conn_Protocol_Case, self).__init__(testname)
        self.hostname = hostname
        self.port = port
        

    def tearDown(self):
        """  Test Name: None -- tearDown function\n\
        Number Connections: N/A \n\
        Procedure: None.  An error here \n\
                   means the server crashed after servicing the request from \n\
                   the previous test.
        """
        if server.poll() is not None:
            #self.fail("The server has crashed.  Please investigate.")
            print "The server has crashed.  Please investigate."

    def test_http_1_0_compliance(self):
        """  Test Name: test_http_1_0_compliance\n\
        Number Connections: 1 \n\
        Procedure: Writes "GET /loadavg HTTP/1.0\\r\\n" to the server, then \n\
                   checks nothing has been returned, and finishes with the \n\
                   extra "\\r\\n" and checking the data sent back from the \n\
                   server.
        """            
        #Make HTTP connection for the server
        sock = server_check.get_socket_connection(self.hostname, self.port)

        sock.send("GET /loadavg HTTP/1.0\r\n")
        sock.send("Host: " + self.hostname + "\r\n")
        sock.settimeout(1)
        time.sleep(.1)
        try:
            if sock.recv(4096, socket.MSG_PEEK) != '':
                self.fail("The http response was returned too early, before" +\
                " the extra \r\n line.")
        
        except socket.timeout:
            pass

        sock.send("\r\n")
        #If there is a HTTP response, it should be a valid /loadavg
        #response.
        data = ""

        time.sleep(0.1)
        try:
            while sock.recv(4096, socket.MSG_PEEK) != '':
                msg_buffer = sock.recv(4096)
                data = data + msg_buffer

        #Connections close after responses for HTTP/1.0 , therefore a timeout
        #should not occur.
        except socket.timeout:
            self.fail("The server did not respond and close the connection in sufficient time.")
        
        
        data = data.split("\r\n\r\n")
        assert len(data) == 2, \
            "The response could not be parsed, check your use of \\r\\n"
            
        assert server_check.check_loadavg_response(data[1]), \
            "The /loadavg object was not properly returned."
        
        sock.close()
        
        
    def test_http_1_1_compliance(self):
        """  Test Name: test_http_1_1_compliance\n\
        Number Connections: 1 \n\
        Procedure: Ensure a persistent connection by sending two consecutive\n\
                   requests to the server on one connection.
        """ 
        #Make HTTP connection for the server
        self.http_connection = httplib.HTTPConnection(self.hostname, self.port)
        
        #Connect to the server
        self.http_connection.connect()

        for x in range(0, 2):
            #GET request for the object /loadavg
            self.http_connection.request("GET", "/loadavg")
    
            #Get the server's response
            server_response = self.http_connection.getresponse()

            #Check the response status code
            self.assertEqual(server_response.status, httplib.OK, "Server failed to respond")

            #Check the data included in the server's response
            self.assertTrue(server_check.check_loadavg_response(server_response.read()), \
                "loadavg check failed")

        self.http_connection.close()




##############################################################################
## Class: Single_Conn_Malicious_Case
## Test cases that are attempting to break down the server
##############################################################################

class Single_Conn_Malicious_Case( Doc_Print_Test_Case ):
    """
    Test case for a single connection, using particularly malicious requests
    that are designed to seek out leaks and points that lack robustness.
    Each case should be handled without the server crashing.
    """
    
    def __init__(self, testname, hostname, port):
        """
        Prepare the test case for creating connections.
        """
        super(Single_Conn_Malicious_Case, self).__init__(testname)
        self.hostname = hostname
        self.port = port
    
    def setUp(self):
        """  Test Name: None -- setUp function\n\
        Number Connections: N/A \n\
        Procedure: Nothing to do here
        """

    def tearDown(self):
        """  Test Name: None -- tearDown function\n\
        Number Connections: N/A \n\
        Procedure: An error here \
                   means the server crashed after servicing the request from \
                   the previous test.
        """

        if server.poll() is not None:
            #self.fail("The server has crashed.  Please investigate.")
            print "The server has crashed.  Please investigate."
        

    def test_file_descriptor_leak(self):
        """  Test Name: test_file_descriptor_leak\n\
        Number Connections: 2000, but only one is connected at a time \n\
        Procedure: 2000 connections are processed as follows: \n\
            1.  Make the connection\n\
            2.  Test a /loadavg request\n\
            3.  Close the connection\n\
        IMPORTANT NOTE: May also thread/fork-bomb your server!
        """
        start = time.time()
        for x in range(2000):
            http_connection = httplib.HTTPConnection(hostname, port)
            # avoid TCP listen overflows
            http_connection.connect()
            http_connection.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 1))
            
            #GET request for the object /loadavg
            http_connection.request("GET", "/loadavg")

            #Get the server's response
            server_response = http_connection.getresponse()

            #Check the response status code
            assert server_response.status == httplib.OK, "Server failed to respond"

            #Check the data included in the server's response
            assert server_check.check_loadavg_response(server_response.read()), \
                "loadavg check failed"
            http_connection.close()
            if time.time() - start > 60:
                raise Error, "Timeout - took more than 60 seconds"
    
    def test_file_descriptor_early_disco_leak_1(self):
        """  Test Name: test_file_descriptor_early_disco_leak_1\n\
        Number Connections: 2000, but only one is connected at a time \n\
        Procedure: 2000 connections are processed as follows: \n\
            1.  Make the connection\n\
            2.  Send to the server: GET /loadavg HTTP/1.1\\r\\n\n\
                  NOTE: Only ONE \\r\\n is sent!\n\
            3.  Close the connection\n\
        IMPORTANT NOTE: May also thread/fork-bomb your server!
        """
        #Test note: the failure will be induced if server_check.get_socket_connection
        #is unable to create a new connection, and an assertion error is thrown
        start = time.time()
        for x in range(2000):
            socket = server_check.get_socket_connection(self.hostname, self.port)
            
            #Write to the server
            socket.send("GET /loadavg HTTP/1.1\r\n")
            socket.send("Host: " + self.hostname + "\r\n")
            #Close the socket
            socket.close()
            if time.time() - start > 60:
                raise Error, "Timeout - took more than 60 seconds"

    def test_file_descriptor_early_disco_leak_2(self):
        """  Test Name: test_file_descriptor_early_disco_leak_2\n\
        Number Connections: 2000, but only one is connected at a time \n\
        Procedure: 2000 connections are processed as follows: \n\
            1.  Make the connection\n\
            2.  Send to the server: GET /loadavg HTTP/1.1\n\
                  NOTE: NO \\r\\n's are sent!\n\
            3.  Close the connection\n\
        IMPORTANT NOTE: May also thread/fork-bomb your server!
        """
        
        #Test note: the failure will be induced if server_check.get_socket_connection
        #is unable to create a new connection, and an assertion error is thrown
        start = time.time()
        for x in range(2000):
            socket = server_check.get_socket_connection(self.hostname, self.port)
            
            #Write to the server
            socket.send("GET /loadavg HTTP/1.1")

            #Close the socket
            socket.close()
            if time.time() - start > 60:
                raise Error, "Timeout - took more than 60 seconds"




    def test_80_kb_URI(self):
        """  Test Name: test_80_kb_URI\n\
        Number Connections: 1\n\
        Procedure: Send a GET request for a URI object that is 80kb long.\n\
                   Then check that another connection and request can still\n\
                   be made.  Also, ensure that an appropriate response is\n\
                   sent to the 80kb request.\n\
        """
        
        sock = server_check.get_socket_connection(self.hostname, self.port)

        sock.send("GET ")
        
        for x in range(1, 10240):
            sock.send("/loadavg")
        
        sock.send(" HTTP/1.1\r\n")
        sock.send("Host: " + self.hostname + "\r\n\r\n")
        
        #If there is a HTTP response, it should NOT be a valid /loadavg
        #response.  All other responses are fine, including closing the
        #connection, so long as the server continues serving other connections
        sock.settimeout(1)
        data = ""

        time.sleep(0.1)
        try:
            while sock.recv(4096, socket.MSG_PEEK) != '':
                msg_buffer = sock.recv(4096)
                data = data + msg_buffer

        #Socket timeouts are not expected for HTTP/1.0 , therefore an open
        #connection is bad.
        except socket.timeout:
            pass
        
        
        data = data.split("\r\n\r\n")

        try:
            if len(data) >= 2 and server_check.check_loadavg_response(data[1]):
                self.fail("A valid /loadavg object was returned for an invalid request.")

        #If an error is generated, it comes from trying to an interpret a JSON
        #object that doesn't exist.
        except (AssertionError, ValueError):
            pass

        
        sock.close()
        
        #Make HTTP connection for the server
        self.http_connection = httplib.HTTPConnection(self.hostname, self.port)
        
        #Connect to the server
        self.http_connection.connect()


        #GET request for the object /loadavg
        self.http_connection.request("GET", "/loadavg")

        #Get the server's response
        server_response = self.http_connection.getresponse()

        #Check the response status code
        self.assertEqual(server_response.status, httplib.OK, "Server failed to respond")

        #Check the data included in the server's response
        self.assertTrue(server_check.check_loadavg_response(server_response.read()), \
            "loadavg check failed")
        
        self.http_connection.close()



    def test_byte_wise_request(self):
        """  Test Name: test_byte_wise_request\n\
        Number Connections: 1\n\
        Procedure: Send a request for GET /loadavg HTTP/1.1 byte by byte.\n\
        """
        
        #Make the low-level connection
        sock = server_check.get_socket_connection(self.hostname, self.port)
        
        for x in "GET /loadavg HTTP/1.0\r\nHost: " + self.hostname + "\r\n":
            sock.send(x)
            time.sleep(0.1)

        sock.settimeout(1)
        msg_buffer = ''
        try:
            if sock.recv(4096, socket.MSG_PEEK) != '':
                self.fail("Data was returned before the extra \r\n")
                
        #We want nothing back until after we've sent the last \r\n
        except socket.timeout:
            pass

        if msg_buffer != '':
            self.fail("The server responded before the full request was sent.")

        sock.send("\r")
        sock.send("\n")

        time.sleep(0.1)
        #Collect the response
        try:
            while sock.recv(4096, socket.MSG_PEEK) != '':
                data = sock.recv(4096)
                msg_buffer = msg_buffer + data
        except socket.timeout:
            self.fail("The socket timed out on responding to the message.")
        
        #Check the response
        data = data.split("\r\n\r\n")

        if len(data) == 2 and server_check.check_loadavg_response(data[1]):
            pass
        elif len(data) != 2:
            self.fail("The server did not return the proper loadavg data")
        else:
            self.fail("A proper loadavg object was not returned.")
        
        sock.close()
    



##############################################################################
## Class: Single_Conn_Bad_Case
## Test cases that aim for various errors in well-formed queries.
##############################################################################

class Single_Conn_Bad_Case(Doc_Print_Test_Case):
    """
    Test case for a single connection, using bad requests that are
    well formed.  The tests are aptly named for describing their effects.
    Each case should be handled gracefully and without the server crashing.
    """

    def __init__(self, testname, hostname, port):
        """
        Prepare the test case for creating connections.
        """
        super(Single_Conn_Bad_Case, self).__init__(testname)
        self.hostname = hostname
        self.port = port
        
        #Prepare the a_string for query checks
        self.a_string = "aaaaaaaaaaaaaaaa"
        for x in range(0, 6):
            self.a_string = self.a_string + self.a_string;

    def setUp(self):
        """  Test Name: None -- setUp function\n\
        Number Connections: N/A \n\
        Procedure: Opens the HTTP connection to the server.  An error here \
                   means the script was unable to create a connection to the \
                   server.
        """
        #Make HTTP connection for the server
        self.http_connection = httplib.HTTPConnection(self.hostname, self.port)
        
        #Connect to the server
        self.http_connection.connect()
    
    def tearDown(self):
        """  Test Name: None -- tearDown function\n\
        Number Connections: N/A \n\
        Procedure: Closes the HTTP connection to the server.  An error here \
                   means the server crashed after servicing the request from \
                   the previous test.
        """
        #Close the HTTP connection
        self.http_connection.close()
        if server.poll() is not None:
            #self.fail("The server has crashed.  Please investigate.")
            print "The server has crashed.  Please investigate."

    def test_404_not_found_1(self):
        """  Test Name: test_404_not_found_1\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request for an illegal object URL:\n\
            GET /junk HTTP/1.1
        """
        server_check.run_404_check(self.http_connection, "/junk", self.hostname)


    def test_404_not_found_2(self):
        """  Test Name: test_404_not_found_2\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request for an illegal object URL:\n\
            GET /loadavg/junk HTTP/1.1
        """
        server_check.run_404_check(self.http_connection, "/loadavg/junk", self.hostname)


    def test_404_not_found_3(self):
        """  Test Name: test_404_not_found_3\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request for an illegal object URL:\n\
            GET /meminfo/junk HTTP/1.1
        """
        server_check.run_404_check(self.http_connection, "/meminfo/junk", self.hostname)


    def test_404_not_found_4(self):
        """  Test Name: test_404_not_found_4\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request for an illegal object URL:\n\
            GET /junk/meminfo HTTP/1.1
        """
        server_check.run_404_check(self.http_connection, "/junk/meminfo", self.hostname)


    def test_404_not_found_5(self):
        """  Test Name: test_404_not_found_5\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request for an illegal object URL:\n\
            GET /junk/loadavg HTTP/1.1
        """
        server_check.run_404_check(self.http_connection, "/junk/loadavg", self.hostname)


    def test_404_not_found_6(self):
        """  Test Name: test_404_not_found_6\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request for an illegal object URL:\n\
            GET /loadavgjunk HTTP/1.1
        """
        server_check.run_404_check(self.http_connection, "/loadavgjunk", self.hostname)


    def test_404_not_found_7(self):
        """  Test Name: test_404_not_found_7\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request for an illegal object URL:\n\
            GET /meminfojunk HTTP/1.1
        """
        server_check.run_404_check(self.http_connection, "/meminfojunk", self.hostname)


    def test_query_string_1(self):
        """  Test Name: test_query_string_1\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /loadavg?notcallback=false HTTP/1.1
        """
        server_check.run_query_check(self.http_connection, "/loadavg?notcallback=false", "loadavg", None, self.hostname)


    def test_query_string_2(self):
        """  Test Name: test_query_string_2\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /loadavg?callback=true&notcallback=false HTTP/1.1
        """
        server_check.run_query_check(self.http_connection, "/loadavg?callback=true&notcallback=false", "loadavg", "true", self.hostname)


    def test_query_string_3(self):
        """  Test Name: test_query_string_3\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /loadavg?notcallback=false&callback=true HTTP/1.1
        """
        server_check.run_query_check(self.http_connection, "/loadavg?notcallback=false&callback=true", "loadavg", "true", self.hostname)


    def test_query_string_4(self):
        """  Test Name: test_query_string_4\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /loadavg?notcallback=false&callback=true&alsonotcallback=false HTTP/1.1
        """
        server_check.run_query_check(self.http_connection, "/loadavg?notcallback=false&callback=true&alsonotcallback=false", "loadavg", "true", self.hostname)


    def test_query_string_5(self):
        """  Test Name: test_query_string_5\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /loadavg?aaa...(1024 a's)...aa=false HTTP/1.1
        """
        server_check.run_query_check(self.http_connection, "/loadavg?aaaa" + self.a_string + "aa=false", "loadavg", None, self.hostname)


    def test_query_string_6(self):
        """  Test Name: test_query_string_6\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /loadavg?aaa...(1024 a's)...aa=false&callback=true HTTP/1.1
        """
        server_check.run_query_check(self.http_connection, "/loadavg?aaa" + self.a_string + "aa=false&callback=true", "loadavg", "true", self.hostname)


    def test_query_string_7(self):
        """  Test Name: test_query_string_7\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /meminfo?notcallback=false HTTP/1.1
        """
        server_check.run_query_check(self.http_connection, "/meminfo?notcallback=false", "meminfo", None, self.hostname)


    def test_query_string_8(self):
        """  Test Name: test_query_string_8\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /meminfo?callback=true&notcallback=false HTTP/1.1
        """
        server_check.run_query_check(self.http_connection, "/meminfo?callback=true&notcallback=false", "meminfo", "true", self.hostname)


    def test_query_string_9(self):
        """  Test Name: test_query_string_9\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /meminfo?notcallback=false&callback=true HTTP/1.1
        """
        server_check.run_query_check(self.http_connection, "/meminfo?notcallback=false&callback=true", "meminfo", "true", self.hostname)


    def test_query_string_10(self):
        """  Test Name: test_query_string_10\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /meminfo?notcallback=false&callback=true&alsonotcallback=false HTTP/1.1
        """
        server_check.run_query_check(self.http_connection, "/meminfo?notcallback=false&callback=true&alsonotcallback=false", "meminfo", "true", self.hostname)


    def test_query_string_11(self):
        """  Test Name: test_query_string_11\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /meminfo?aaa...(1024 a's)...aa=false HTTP/1.1
        """  
        server_check.run_query_check(self.http_connection, "/meminfo?aaaa" + self.a_string + "aa=false", "meminfo", None, self.hostname)


    def test_query_string_12(self):
        """  Test Name: test_query_string_12\n\
        Number Connections: 1 \n\
        Procedure: Test a simple GET request with a complex query string:\n\
            GET /meminfo?aaa...(1024 a's)...aa=false&callback=true HTTP/1.1
        """  
        server_check.run_query_check(self.http_connection, "/meminfo?aaa" + self.a_string + "aa=false&callback=true", "meminfo", "true", self.hostname)

#    def test_method_check_2(self):
#        """  Test Name: test_method_check_2\n\
#        Number Connections: 1 \n\
#        Procedure: Test a request using no method in the request:\n\
#             /loadavg HTTP/1.1
#        """
#        server_check.run_method_check(self.http_connection, "", self.hostname)

#Note for future: consider making the method requested VERY long
#    
#    def test_method_check_3(self):
#        """  Test Name: test_method_check_3\n\
#        Number Connections: 1 \n\
#        Procedure: Test a request using a different method than GET:\n\
#            THISISALONGREQUESTMETHODTOUSEFOROURSERVERSHERE /loadavg HTTP/1.1
#        """
#        server_check.run_method_check(self.http_connection, "THISISALONGREQUESTMETHODTOUSEFOROURSERVERSHERE", self.hostname)
    
    def test_method_check_4(self):
        """  Test Name: test_method_check_4\n\
        Number Connections: 1 \n\
        Procedure: Test a request using a different method than GET:\n\
            ASD /loadavg HTTP/1.1
        """
        server_check.run_method_check(self.http_connection, "ASD", self.hostname)
    




class Multi_Conn_Sequential_Case(Doc_Print_Test_Case):
    """
    Test case for multiple connections, using good requests that are properly
    formed.  Further, the requests are processed sequentially.
    The tests are aptly named for describing their effects.
    """
    
    def __init__(self, testname, hostname, port):
        """
        Prepare the test case for creating connections.
        """
        super(Multi_Conn_Sequential_Case, self).__init__(testname)
        self.hostname = hostname
        self.port = port
    
    def setUp(self):
        """  Test Name: None -- setUp function\n\
        Number Connections: N/A \n\
        Procedure: Opens the HTTP connection to the server.  An error here \
                   means the script was unable to create a connection to the \
                   server.
        """
        self.http_connections = []
    
    def tearDown(self):
        """  Test Name: None -- tearDown function\n\
        Number Connections: N/A \n\
        Procedure: Closes the HTTP connection to the server.  An error here \
                   means the server crashed after servicing the request from \
                   the previous test.
        """
        for http_conn in self.http_connections:
            http_conn.close()
        if server.poll() is not None:
            #self.fail("The server has crashed.  Please investigate.")
            print "The server has crashed.  Please investigate."

    def test_two_connections(self):
        """  Test Name: test_two_connections\n\
        Number Connections: 2 \n\
        Procedure: Run 2 connections simultaneously for simple GET requests:\n\
            GET /loadavg HTTP/1.1
        """
        
        #Append two connections to the list
        for x in range(2):
            self.http_connections.append(httplib.HTTPConnection(self.hostname,
                                                                self.port))
        #Connect each connection
        for http_conn in reversed(self.http_connections):
            http_conn.connect()
        
        #Run a request for /loadavg and check it
        for http_conn in reversed(self.http_connections):
            server_check.run_connection_check_loadavg(http_conn, self.hostname)
        
        #Re-connect in the case of HTTP/1.0 protocol implementation
        for http_conn in self.http_connections:
            http_conn.connect()
        
        #Run a request for /loadavg and check it
        for http_conn in self.http_connections:
            server_check.run_connection_check_loadavg(http_conn, self.hostname)

    def test_four_connections(self):
        """  Test Name: test_four_connections\n\
        Number Connections: 4 \n\
        Procedure: Run 4 connections simultaneously for simple GET requests:\n\
            GET /loadavg HTTP/1.1
        """
        
        #Append four connections to the list
        for x in range(4):
            self.http_connections.append(httplib.HTTPConnection(self.hostname,
                                                                self.port))

        #Connect each connection
        for http_conn in reversed(self.http_connections):
            http_conn.connect()
        
        #Run a request for /loadavg and check it
        for http_conn in reversed(self.http_connections):
            server_check.run_connection_check_loadavg(http_conn, self.hostname)
        
        #Re-connect in the case of HTTP/1.0 protocol implementation
        for http_conn in self.http_connections:
            http_conn.connect()
        
        #Run a request for /loadavg and check it
        for http_conn in self.http_connections:
            server_check.run_connection_check_loadavg(http_conn, self.hostname)
            
    def test_eight_connections(self):
        """  Test Name: test_eight_connections\n\
        Number Connections: 8 \n\
        Procedure: Run 8 connections simultaneously for simple GET requests:\n\
            GET /loadavg HTTP/1.1
        """
        
        
        #Append eight connections to the list
        for x in range(8):
            self.http_connections.append(httplib.HTTPConnection(self.hostname,
                                                                self.port))

        #Connect each connection
        for http_conn in reversed(self.http_connections):
            http_conn.connect()
        
        #Run a request for /loadavg and check it
        for http_conn in reversed(self.http_connections):
            server_check.run_connection_check_loadavg(http_conn, self.hostname)
        
        #Re-connect in the case of HTTP/1.0 protocol implementation
        for http_conn in self.http_connections:
            http_conn.connect()
        
        #Run a request for /loadavg and check it
        for http_conn in self.http_connections:
            server_check.run_connection_check_loadavg(http_conn, self.hostname)
        
        
    
class Single_Conn_Good_Case(Doc_Print_Test_Case):
    
    """
    Test case for a single connection, using good requests that are properly
    formed.  The tests are aptly named for describing their effects.
    """

    def __init__(self, testname, hostname, port):
        """
        Prepare the test case for creating connections.
        """
        super(Single_Conn_Good_Case, self).__init__(testname)
        
        self.hostname = hostname
        self.port = port

    def setUp(self):
        """  Test Name: None -- setUp function\n\
        Number Connections: N/A \n\
        Procedure: Opens the HTTP connection to the server.  An error here \
                   means the script was unable to create a connection to the \
                   server.
        """
        #Make HTTP connection for the server
        self.http_connection = httplib.HTTPConnection(self.hostname, self.port)
        
        #Connect to the server
        self.http_connection.connect()
    
    def tearDown(self):
        """  Test Name: None -- tearDown function\n\
        Number Connections: N/A \n\
        Procedure: Closes the HTTP connection to the server.  An error here \
                   means the server crashed after servicing the request from \
                   the previous test.
        """
        #Close the HTTP connection
        self.http_connection.close()
        if server.poll() is not None:
            #self.fail("The server has crashed.  Please investigate.")
            print "The server has crashed.  Please investigate."


    def test_loadavg_no_callback(self):
        """  Test Name: test_loadavg_no_callback\n\
        Number Connections: One \n\
        Procedure: Simple GET request:\n\
            GET /loadavg HTTP/1.1
        """
        
        #GET request for the object /loadavg
        self.http_connection.request("GET", "/loadavg")

        #Get the server's response
        server_response = self.http_connection.getresponse()

        #Check the response status code
        self.assertEqual(server_response.status, httplib.OK, "Server failed to respond")

        #Check the data included in the server's response
        self.assertTrue(server_check.check_loadavg_response(server_response.read()), \
            "loadavg check failed")


    def test_meminfo_no_callback(self):
        """  Test Name: test_meminfo_no_callback\n\
        Number Connections: One \n\
        Procedure: Simple GET request:\n\
            GET /meminfo HTTP/1.1
        """
    
        #GET request for the object /meminfo
        self.http_connection.request("GET", "/meminfo")

        #Get the server's response
        server_response = self.http_connection.getresponse()

        #Check the response status code
        self.assertEqual(server_response.status, httplib.OK, "Server failed to respond")

        #Check the data included in the server's response
        self.assertTrue(server_check.check_meminfo_response(server_response.read()), \
            "meminfo check failed")
           

    def test_loadavg_callback(self):
        """  Test Name: test_loadavg_callback\n\
        Number Connections: One \n\
        Procedure: GET request with callback:\n\
            GET /loadavg?callback=callbackmethod HTTP/1.1
        """
        
        #GET request for the object /loadavg
        self.http_connection.request("GET", "/loadavg?callback=callbackmethod")

        #Get the server's response
        server_response = self.http_connection.getresponse()

        #Check the response status code
        self.assertEqual(server_response.status, httplib.OK, "Server failed to respond")

        #Check the data included in the server's response
        self.assertTrue(server_check.check_callback_response(server_response.read(), 
            "callbackmethod", "loadavg"), "loadavg callback check failed")
            
            
           
    def test_meminfo_callback(self):
        """  Test Name: test_meminfo_callback\n\
        Number Connections: One \n\
        Procedure: GET request with callback:\n\
            GET /meminfo?callback=callbackmethod HTTP/1.1
        """
        
        #GET request for the object /meminfo
        self.http_connection.request("GET", "/meminfo?callback=callbackmethod")

        #Get the server's response
        server_response = self.http_connection.getresponse()

        #Check the response status code
        self.assertEqual(server_response.status, httplib.OK, "Server failed to respond")

        #Check the data included in the server's response
        self.assertTrue(server_check.check_callback_response(server_response.read(), 
            "callbackmethod", "meminfo"), "meminfo callback check failed")



###############################################################################
#Globally define the Server object so it can be checked by all test cases
###############################################################################
server = None
output_file = None
###############################################################################
#Define an atexit shutdown method that kills the server as needed
###############################################################################
def clean_up_testing():
    try:
        os.kill(server.pid, signal.SIGTERM)
    except:
        pass

#Grade distribution constants
grade_points_available = 90
# 6 tests
minreq_total = 40
# 27 tests
extra_total = 27
# 5 tests
malicious_total = 20
# 4 tests
ipv6_total = 8
    
def print_points(minreq, extra, malicious, ipv6):
    """All arguments are fractions (out of 1)"""
    print "Minimum Requirements:         \t%2d/%2d" % (int(minreq * minreq_total), minreq_total)
    print "IPv6 Functionality:           \t%2d/%2d" % (int(ipv6 * ipv6_total), ipv6_total)
    print "Extra Tests:                  \t%2d/%2d" % (int(extra * extra_total), extra_total)
    print "Robustness:                   \t%2d/%2d" % (int(malicious * malicious_total), malicious_total)

###############################################################################
# Main
###############################################################################
#Not sure if this is necessary
if __name__ == '__main__':

    try:
        opts, args = getopt.getopt(sys.argv[1:], "hs:t:o:l", \
            ["help"])
    except getopt.GetoptError, err:
        # print help information and exit:
        print str(err) # will print something like "option -a not recognized"
        usage()
        sys.exit(2)

    server_path = None
    individual_test = None
    runIPv6 = True
    list_tests = False
    
    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-s"):
            server_path = a
        elif o in ("-t"):
            individual_test = a
        elif o in ("-l"):
            list_tests = True
        elif o in ("-o"):
            output_file = a
        else:
            assert False, "unhandled option"

    alltests = [Single_Conn_Good_Case, Multi_Conn_Sequential_Case, Single_Conn_Bad_Case, Single_Conn_Malicious_Case, Single_Conn_Protocol_Case]

    def findtest(tname):
        for clazz in alltests:
            if tname in dir(clazz):
                return clazz
        return None

    if list_tests:
        for clazz in alltests:
            print "In:", clazz.__name__
            for test in [m for m in dir(clazz) if m.startswith("test_")]:
                print "\t", test

        sys.exit(1)
    
    if server_path is None:
        usage()
        sys.exit()
        
    
    #Open the output file if possible
    if output_file is not None:
        output_file = file(output_file, "w")
    
    #Check access to the server path
    if not os.access(server_path, os.R_OK):
        print "File ", server_path, " is not readable"
        sys.exit(1)

    #Setting the default timeout to allow connections to time out
    socket.setdefaulttimeout(4)
    
    #Determine the hostname for running the server locally
    hostname = socket.gethostname()
    
    #Determine the port number to use, based off of the current PID.
    port = (os.getpid() % 10000) + 20000

    if output_file is not None:
        #Open the server on this machine, with port 10305.
        server = subprocess.Popen([server_path,"-p", str(port)], stdout=output_file, stderr=subprocess.STDOUT)
    else:
        server = subprocess.Popen([server_path,"-p", str(port)])

    #Register the atexit function to shutdown the server on Python exit
    atexit.register(clean_up_testing)
    
    #Ensure that the server is running and accepting connections.
    counter = 0
    while True:
        try:
            http_conn = httplib.HTTPConnection(hostname, port)
            http_conn.connect()
            http_conn.close()
            break
        except:
            if counter >= 10:
                print "The server is not responding to connection requests, and\
may not be functioning properly.  Ensure that you sent the proper location for\
your server, and that your server starts running in a reasonable amount of time\
(this waited 5 seconds for your server to start running).\n\nIn the case that \
your server works fine and there's an error in our script, please use the 'ps'\
command to see if the server is still running, and let us know if there is an\
issue with our script creating a runaway process."
                sys.exit(1)
            counter += 1
            time.sleep(.5)
    
    print "Your server has started successfully.  Now to begin testing."

    #If an individual test was requested, find that test and only add it.  If no
    #tests are found of that name, error and exit.
    if individual_test is not None:

        single_test_suite = unittest.TestSuite()
        testclass = findtest(individual_test)
        if testclass:
            single_test_suite.addTest(testclass(individual_test, hostname, port))
        else:
            print "The test \"" + individual_test + "\" was not found in the test classes. Use -l."
            sys.exit(1)

        #Run the single test test suite and store the results
        test_results = unittest.TextTestRunner().run(single_test_suite)

        if test_results.wasSuccessful():
            print "Test: " + individual_test + " passed!"
        else:
            print "Test: " + individual_test + " failed."

    else:


        #Test Suite for the minimum requirements
        min_req_suite = unittest.TestSuite()
    
        #Add all of the tests from the class Single_Conn_Good_Case
        for test_function in dir(Single_Conn_Good_Case):
            if test_function.startswith("test_"):
                min_req_suite.addTest(Single_Conn_Good_Case(test_function, hostname, port))
        
        
    
        #In particular, add the two-connection test from Multi_Conn_Sequential_Case,
        #and the 1.0 protocol check (early return check) from Single_Conn_Protocol_Case
        min_req_suite.addTest(Multi_Conn_Sequential_Case("test_two_connections", hostname, port)) 
        min_req_suite.addTest(Single_Conn_Protocol_Case("test_http_1_0_compliance", hostname, port))



        #Test Suite for extra points, mostly testing error cases
        extra_tests_suite = unittest.TestSuite()

    
        #Add all of the tests from the class Multi_Conn_Sequential_Case
        for test_function in dir(Multi_Conn_Sequential_Case):
            if test_function.startswith("test_"):
                extra_tests_suite.addTest(Multi_Conn_Sequential_Case(test_function, hostname, port))
    

        #Add all of the tests from the class Single_Conn_Bad_Case
        for test_function in dir(Single_Conn_Bad_Case):
            if test_function.startswith("test_"):
                extra_tests_suite.addTest(Single_Conn_Bad_Case(test_function, hostname, port)) 
   
        #In particular, add the 1.1 protocol persistent connection check from Single_Conn_Protocol_Case
        extra_tests_suite.addTest(Single_Conn_Protocol_Case("test_http_1_1_compliance", hostname, port))


        #Malicious Test Suite
        malicious_tests_suite = unittest.TestSuite()
        
        #Add all of the tests from the class Single_Conn_Malicious_Case
        for test_function in dir(Single_Conn_Malicious_Case):
            if test_function.startswith("test_"):
                malicious_tests_suite.addTest(Single_Conn_Malicious_Case(test_function, hostname, port))  


        print 'Beginning the Minimum Requirement Tests'
        time.sleep(1)
        #Run the minimum requirements test suite and store the results
        test_results = unittest.TextTestRunner().run(min_req_suite)

        nt = min_req_suite.countTestCases()
        minreq_score = max(0, F(nt - len(test_results.errors) - len(test_results.failures), nt))

        #Check if the server passed the minimum requirements
        if test_results.wasSuccessful():
            print "\nYou have passed the Minimum Requirements for this project!\n"
        else:
            print "\nYou have NOT passed the Minimum Requirements for this project.\n"+\
                "Please examine the above errors, the Malicious and Extra Tests\n"+\
                "will not be run until the above tests pass.\n"
                
            print_points(minreq_score, 0, 0, 0)
            sys.exit()

        #IPv6 Test Suite
        ipv6_test_suite = unittest.TestSuite()
        #Add all of the tests from the class Single_Conn_Good_Case
        for test_function in dir(Single_Conn_Good_Case):
            if test_function.startswith("test_"):
                ipv6_test_suite.addTest(Single_Conn_Good_Case(test_function, "localhost6", port))

        if runIPv6:
            test_results = unittest.TextTestRunner().run(ipv6_test_suite)
            ipv6_score = max(0, F(ipv6_test_suite.countTestCases() - len(test_results.errors) - len(test_results.failures), ipv6_test_suite.countTestCases()))

            if test_results.wasSuccessful():
                print "\nCongratulations! IPv6 support appears to work!\n"
            else:
                print "\nYou have NOT passed the IPv6 portion.  Check that your code is protocol-independent and binds to the IPv6 address.  " +\
                "Please examine the errors listed above.\n"
                
                
        print 'Beginning the Extra Tests'
        time.sleep(1)
        #Run the extra tests
        test_results = unittest.TextTestRunner().run(extra_tests_suite)
    
        extra_score = max(0, F(extra_tests_suite.countTestCases() - len(test_results.errors) - len(test_results.failures), extra_tests_suite.countTestCases()))

        #Check if the server passed the extra tests
        if test_results.wasSuccessful():
            print "\nYou have passed the Extra Tests for this project!\n"
        else:
            print "\nYou have NOT passed the Extra Tests for this project.\n"+\
                "Please examine the above errors, the Malicious Tests\n"+\
                "will not be run until the above tests pass.\n"
                
            print_points(minreq_score, extra_score, 0, ipv6_score)
            sys.exit()
        
        
        
        print "Now running the MALICIOUS Tests.  WARNING:  These tests will not necessarily run fast!"
        #Run the malicious tests
        test_results = unittest.TextTestRunner().run(malicious_tests_suite)

        robustness_score = max(0, F(malicious_tests_suite.countTestCases() - len(test_results.errors) - len(test_results.failures), malicious_tests_suite.countTestCases()))

        #Check if the server passed the extra tests
        if test_results.wasSuccessful():
            print "\nCongratulations! You have passed the Malicious Tests!\n"
        else:
            print "\nYou have NOT passed one or more of the Malicious Tests.  " +\
                  "Please examine the errors listed above.\n"
            
        print_points(minreq_score, extra_score, robustness_score, ipv6_score)
