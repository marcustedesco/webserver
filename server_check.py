#!/usr/bin/python
#
# This is a quick and sloppy test driver that will execute tests on an http
# server developed by students of cs3214.  This will be later revised.  The main
# package in use is httplib , which will be used to manually send requests to
# the server.
#
#
#

import sys
import httplib, json, os, threading, socket, getopt, unittest, re, time, struct




def usage():
    print """
    Usage: python serv_test_driver.py -s [server] -p [port] 
        -h              Show help 
        -s server       Connect to location server
        -p port         Set the port to use for the server
          """
       
          

def get_socket_connection(hostname, port):
    """
    Connect to a server at hostname on the supplied port, and return the socket
    connection to the server.
    """
    for res in socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM):
        family, sockettype, protocol, canonname, socketaddress = res
        try:
            sock = socket.socket(family, sockettype, protocol)
            sock.settimeout(10)
            # avoid TCP listen overflows when making back-to-back requests 
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 1))

        except socket.error, msg:
            sock = None
            continue
        
        try:
            sock.connect(socketaddress)
        except socket.error, msg:
            sock.close()
            sock = None
            continue
            
        break

    if sock is None:
        raise ValueError('The script was unable to open a socket to the server')
    else:
        return sock
    
    
              
def run_connection_check_loadavg(http_conn, hostname):
    """
    Run a check of the connection for validity, using a well-formed
    request for /loadavg and checking it after receiving it.
    """
    
    #GET request for the object /loadavg
    http_conn.request("GET", "/loadavg", headers={"Host":hostname})

    #Get the server's response
    server_response = http_conn.getresponse()

    #Check the response status code
    assert server_response.status == httplib.OK, "Server failed to respond"

    #Check the data included in the server's response
    assert check_loadavg_response(server_response.read()), \
        "loadavg check failed"



def run_404_check(http_conn, obj, hostname):
    """
    Checks that the server properly generates a 404 status message when
    requesting a non-existent URL object.
    """
    
    #GET request for the object /loadavg
    http_conn.request("GET", obj, headers={"Host":hostname})

    #Get the server's response
    server_response = http_conn.getresponse()

    #Check the response status code
    assert server_response.status == httplib.NOT_FOUND, \
        "Server failed to respond with a 404 status for obj=" + obj + ", gave response: " + str(server_response.status)
    server_response.read()



def run_query_check(http_conn, request, req_object, callback, hostname):
    """
    Checks that the server properly processes the query string passed to it.
    """

    http_conn.request("GET", request, headers={"Host":hostname})
    server_response = http_conn.getresponse()
    assert server_response.status == httplib.OK, "Server failed to respond"
    
    if callback is None:
        if req_object == "loadavg":
            assert check_loadavg_response(server_response.read()), \
                "loadavg check failed"
        else:
            assert check_meminfo_response(server_response.read()), \
                "meminfo check failed"
    else:
        assert check_callback_response(server_response.read(), 
            callback, req_object), "callback check failed"



def run_method_check(http_conn, method, hostname):
    """
    Check that the unsupported method supplied has either a NOT IMPLEMENTED
    or METHOD NOT ALLOWED response from the server.
    """
    
    http_conn.request(method, "/loadavg", headers={"Host":hostname})
    server_response = http_conn.getresponse()
    assert (server_response.status == httplib.METHOD_NOT_ALLOWED or
        server_response.status == httplib.NOT_IMPLEMENTED), \
        "Server failed to respond with the METHOD NOT ALLOWED or \
        NOT IMPLEMENTED status for method: " + method + " response was: " \
        + str(server_response.status)
    server_response.read()




def print_response(response):
    """Print the response line by line as returned by the server.  the response
    variable is simply the server_response.read(), and this function prints out
    each line of the output.  Most helpful for printing an actual web page. """

    lines = response.split("\n")
    for line in lines:
        print line.strip()



def check_loadavg_response(response):
    """Check that the response to a loadavg request generated the correctly
    formatted output.  Returns true if it executes properly, throws an
    AssertionError if it does not execute properly or another error if json
    is unable to decode the response."""

    try:
        data = json.loads(response.strip())
    except ValueError, msg:
	raise AssertionError("Invalid JSON object.  Received: " + response)
	

    assert len(data) == 3, "Improper number of data items returned"

    assert data.has_key('total_threads'), "total_threads element missing"
    assert data.has_key('loadavg'), "loadavg element missing"
    assert data.has_key('running_threads'), "running_threads element missing"

    assert len(data['loadavg']) == 3, 'Improper number of data items in \
        loadavg'
        
    return True



def check_meminfo_response(response):
    """Check that the response to a meminfo request generated the correctly
    formatted output.  Returns true if it executes properly, throws an
    AssertionError if it does not execute properly or another error if json
    is unable to decode the response."""

    try:
        data = json.loads(response.strip())
    except ValueError, msg:
	raise AssertionError("Invalid JSON object.  Received: " + response)

    for line in open("/proc/meminfo"):
                entry = re.split(":?\s+", line)
                assert data.has_key(entry[0]), entry[0] + " key is missing"

                try:
                    int(data[entry[0]])
                except (TypeError, ValueError):
                    raise AssertionError("a non-integer was passed to meminfo")

    return True



def check_callback_response(response, callback, req_obj):
    """Check that the response to a req_obj request with callback function
    callback generated the correctly formatted output.  Returns true if it 
    executes properly, throws an AssertionError if it does not execute properly
    or another error if json is unable to decode the response."""
    

    callback.replace(' ','')
    response.replace(' ','')
    assert response[0:len(callback)+1] == callback + "(", 'callback incorrect, was: ' + response[0:len(callback)+1] + ' , expected: ' + callback + '('
    assert response[len(response)-1] == ")", 'missing close parenthesis'

    if req_obj == "meminfo":
        check_meminfo_response(response[len(callback)+1:len(response)-1])
    elif req_obj == "loadavg":
        check_loadavg_response(response[len(callback)+1:len(response)-1])

    return True
