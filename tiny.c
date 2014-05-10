/* $begin tinymain */
/*
 * tiny.c - A simple, iterative HTTP/1.0 Web server that uses the 
 *     GET method to serve static and dynamic content.
 */
#include "csapp.h"
#include <stdio.h>
#include <string.h>
#include <ctype.h>
#include <list.h>
#include <threadpool.h>

void * doit_wrapper(void * connect_fd);
void doit(int fd);
void read_requesthdrs(rio_t *rp);
int parse_uri(char *uri, char *filename, char *cgiargs);
void serve_static(int fd, char *filename, int filesize);
void get_filetype(char *filename, char *filetype);
void serve_dynamic(int fd, char *filename, char *cgiargs);
void serve_loadavg(int fd, char *filename, char *cgiargs);
void serve_meminfo(int fd, char *filename, char *cgiargs);
int isCallbackValid(char * callback);
char * callbackValue(char * callback);
void clienterror(int fd, char *cause, char *errnum, 
		 char *shortmsg, char *longmsg);

pthread_mutex_t mutex;

int main(int argc, char **argv) 
{
    int listenfd, connfd, port, clientlen, c;
    struct sockaddr_in clientaddr;

    /* Check command line args */
    if (argc < 3) {
    	fprintf(stderr, "usage: %s <port>\n", argv[0]);
    	exit(1);
    }

    while((c = getopt(argc, argv, "p:")) != -1){
        switch(c){
            case 'p':
                port = atoi(optarg);
                printf("Port: %i\n", port);
                break;
        }
    }

    signal(SIGPIPE, SIG_IGN);

    listenfd = Open_listenfd(port);
    printf("LISTENFD: %d\n", listenfd);

    struct thread_pool *pool = thread_pool_new(16);
    pthread_mutex_init(&mutex, NULL);

    while (1) {
    	clientlen = sizeof(clientaddr);
    	connfd = Accept(listenfd, (SA *)&clientaddr, &clientlen); //line:netp:tiny:accept

        //fnctl function
        int * connect_ptr = malloc(sizeof(int));
        *connect_ptr = connfd;
        printf("Connection thread started: %d\n", connect_ptr);
        thread_pool_submit(pool, doit_wrapper, (void *)connect_ptr);
        printf("Connection pool submitted: %d\n", connect_ptr);
    	//doit(connfd);                                             //line:netp:tiny:doit
    	//printf("CLOSE CONNECTION\n");
        //Close(connfd);                                            //line:netp:tiny:close
    }
}
/* $end tinymain */

//wrapper to call doit from the threadpool
void * doit_wrapper(void * connect_fd)
{
    int ptr_connect_fd = *((int *)connect_fd);
 
    doit(ptr_connect_fd);
    printf("CLOSE CONNECTION: %d\n", ptr_connect_fd);
    Close(ptr_connect_fd);
   
    free(connect_fd);
 
    return 0;
}


/*
 * doit - handle one HTTP request/response transaction
 */
/* $begin doit */
void doit(int fd) 
{
    int is_static;
    struct stat sbuf;
    char buf[MAXLINE], method[MAXLINE], uri[MAXLINE], version[MAXLINE];
    char filename[MAXLINE], cgiargs[MAXLINE];
    rio_t rio;
  
    /* Read request line and headers */
    Rio_readinitb(&rio, fd);
    Rio_readlineb(&rio, buf, MAXLINE);                   //line:netp:doit:readrequest

    printf("DOIT: %s\n", buf);
    
    sscanf(buf, "%s %s %s", method, uri, version);       //line:netp:doit:parserequest
    if (strcasecmp(method, "GET")) {                     //line:netp:doit:beginrequesterr
       clienterror(fd, method, "501", "Not Implemented",
                "Tiny does not implement this method");
        return;
    }                                                    //line:netp:doit:endrequesterr
    read_requesthdrs(&rio);                              //line:netp:doit:readrequesthdrs

    /* Parse URI from GET request */
    is_static = parse_uri(uri, filename, cgiargs);       //line:netp:doit:staticcheck

    printf("DOIT URI: %s\n", uri);
    printf("DOIT FILENAME: %s\n", filename);
    printf("DOIT CGIARGS: %s\n", cgiargs);


    //if (stat(filename, &sbuf) < 0 && !strstr(filename, "loadavg") && !strstr(filename, "meminfo")) {                     //line:netp:doit:beginnotfound
    if (stat(filename, &sbuf) < 0 && strcmp(filename+2, "loadavg") != 0 && strcmp(filename+2, "meminfo") != 0) {	
        clienterror(fd, filename, "404", "Not found",
    		    "Tiny couldn't find this file");
    	return;
    }                                                    //line:netp:doit:endnotfound

    if (is_static) { /* Serve static content */          
    	if (!(S_ISREG(sbuf.st_mode)) || !(S_IRUSR & sbuf.st_mode)) { //line:netp:doit:readable
    	    clienterror(fd, filename, "403", "Forbidden",
    			"Tiny couldn't read the file");
    	    return;
    	}
    	serve_static(fd, filename, sbuf.st_size);        //line:netp:doit:servestatic
    }
    else if(strstr(filename, "loadavg")){
        //printf("filename: %s\n", filename);
        //printf("cgiargs: %s\n", cgiargs);
        serve_loadavg(fd, filename, cgiargs);
        //return;
    }

    else if(strstr(filename, "meminfo")){
        serve_meminfo(fd, filename, cgiargs);
        //return;
    }
    else { /* Serve dynamic content */
    	if (!(S_ISREG(sbuf.st_mode)) || !(S_IXUSR & sbuf.st_mode)) { //line:netp:doit:executable
    	    clienterror(fd, filename, "403", "Forbidden",
    			"Tiny couldn't run the CGI program");
    	    return;
    	}

        serve_dynamic(fd, filename, cgiargs);            //line:netp:doit:servedynamic
    }
}
/* $end doit */

/*
 * read_requesthdrs - read and parse HTTP request headers
 */
/* $begin read_requesthdrs */
void read_requesthdrs(rio_t *rp) 
{
    char buf[MAXLINE];

    Rio_readlineb(rp, buf, MAXLINE);
    printf("READ_REQUEST: %s\n", buf);
    while(strcmp(buf, "\r\n")) {          //line:netp:readhdrs:checkterm
    	Rio_readlineb(rp, buf, MAXLINE);
    	printf("%s", buf);
    }
    return;
}
/* $end read_requesthdrs */

/*
 * parse_uri - parse URI into filename and CGI args
 *             return 0 if dynamic content, 1 if static
 */
/* $begin parse_uri */
int parse_uri(char *uri, char *filename, char *cgiargs) 
{
    printf("URI: %s\n", uri);
    printf("FILENAME: %s\n", filename);
    printf("CGIARGS: %s\n", cgiargs);

    char *ptr;

    if (!strstr(uri, "cgi-bin") && !strstr(uri, "loadavg") && !strstr(uri, "meminfo")) {  /* Static content */ //line:netp:parseuri:isstatic
    	strcpy(cgiargs, "");                             //line:netp:parseuri:clearcgi
    	strcpy(filename, ".");                           //line:netp:parseuri:beginconvert1
    	strcat(filename, uri);                           //line:netp:parseuri:endconvert1
    	if (uri[strlen(uri)-1] == '/')                   //line:netp:parseuri:slashcheck
    	    strcat(filename, "home.html");               //line:netp:parseuri:appenddefault
    	return 1;
    }
    else {  /* Dynamic content */                        //line:netp:parseuri:isdynamic
    	ptr = index(uri, '?');                           //line:netp:parseuri:beginextract

    	if (ptr) {
    	    strcpy(cgiargs, ptr+1);
    	    *ptr = '\0';
    	}
    	else 
    	    strcpy(cgiargs, "");                         //line:netp:parseuri:endextract

    	strcpy(filename, ".");                           //line:netp:parseuri:beginconvert2
    	strcat(filename, uri);                           //line:netp:parseuri:endconvert2
    	return 0;
    }
}
/* $end parse_uri */

/*
 * serve_static - copy a file back to the client 
 */
/* $begin serve_static */
void serve_static(int fd, char *filename, int filesize) 
{
    int srcfd;
    char *srcp, filetype[MAXLINE], buf[MAXBUF];
 
    /* Send response headers to client */
    get_filetype(filename, filetype);       //line:netp:servestatic:getfiletype
    sprintf(buf, "HTTP/1.0 200 OK\r\n");    //line:netp:servestatic:beginserve
    sprintf(buf, "%sServer: Tiny Web Server\r\n", buf);
    sprintf(buf, "%sContent-length: %d\r\n", buf, filesize);
    sprintf(buf, "%sContent-type: %s\r\n\r\n", buf, filetype);
    Rio_writen(fd, buf, strlen(buf));       //line:netp:servestatic:endserve

    /* Send response body to client */
    srcfd = Open(filename, O_RDONLY, 0);    //line:netp:servestatic:open
    srcp = Mmap(0, filesize, PROT_READ, MAP_PRIVATE, srcfd, 0);//line:netp:servestatic:mmap
    Close(srcfd);                           //line:netp:servestatic:close
    Rio_writen(fd, srcp, filesize);         //line:netp:servestatic:write
    Munmap(srcp, filesize);                 //line:netp:servestatic:munmap
}

/*
 * get_filetype - derive file type from file name
 */
void get_filetype(char *filename, char *filetype) 
{
    if (strstr(filename, ".html"))
	strcpy(filetype, "text/html");
    else if (strstr(filename, ".gif"))
	strcpy(filetype, "image/gif");
    else if (strstr(filename, ".jpg"))
	strcpy(filetype, "image/jpeg");
    else
	strcpy(filetype, "text/plain");
}  
/* $end serve_static */

/*
 * serve_dynamic - run a CGI program on behalf of the client
 */
/* $begin serve_dynamic */
void serve_dynamic(int fd, char *filename, char *cgiargs) 
{
    char buf[MAXLINE], *emptylist[] = { NULL };

    /* Return first part of HTTP response */
    sprintf(buf, "HTTP/1.0 200 OK\r\n"); 
    Rio_writen(fd, buf, strlen(buf));
    sprintf(buf, "Server: Tiny Web Server\r\n");
    Rio_writen(fd, buf, strlen(buf));
  
    if (Fork() == 0) { /* child */ //line:netp:servedynamic:fork
    	/* Real server would set all CGI vars here */
    	setenv("QUERY_STRING", cgiargs, 1); //line:netp:servedynamic:setenv
    	Dup2(fd, STDOUT_FILENO);         /* Redirect stdout to client */ //line:netp:servedynamic:dup2
    	Execve(filename, emptylist, environ); /* Run CGI program */ //line:netp:servedynamic:execve
    }
    Wait(NULL); /* Parent waits for and reaps child */ //line:netp:servedynamic:wait
}
/* $end serve_dynamic */


/*
 * serve_loadavg - send loadavg info back to the client 
 */
/* $begin serve_loadavg */
void serve_loadavg(int fd, char *filename, char *cgiargs) 
{
    //int srcfd;
    //char *srcp, filetype[MAXLINE], 
    char buf[MAXBUF];
    buf[0] = '\0';
    //&filetype[0] = "text/html";

    char content[MAXLINE];
    content[0] = '\0';
    //sprintf(content, "");

    printf("cgiargs: %s\n", cgiargs);

    if(!isCallbackValid(cgiargs)){
        sprintf(content, "Invalid arguements");
    }
    else{
        if(callbackValue(cgiargs) != NULL){

            sprintf(content, "%s(", callbackValue(cgiargs));
        }

        FILE* fp;
        double one, five, ten;
        char ratio[32];
        ratio[0] = '\0';
        fp = fopen ("/proc/loadavg", "r");
        fscanf (fp, "%lf %lf %lf %s\n", &one, &five, &ten, &ratio[0]);
        fclose (fp);

        char * running = strtok (ratio,"/");
        char * total = strtok (NULL,"/");

        sprintf(content, "%s{\"total_threads\": \"%s\", \"loadavg\": [\"%.2f\", \"%.2f\", \"%.2f\"], \"running_threads\": \"%s\"}", content, total, one, five, ten, running);
    
        if(callbackValue(cgiargs) != NULL){
            sprintf(content, "%s)", content);
        }
    }

    /* Send response headers to client */
    sprintf(buf, "HTTP/1.0 200 OK\r\n");    //line:netp:servestatic:beginserve
    sprintf(buf, "%sServer: Tiny Web Server\r\n", buf);
    sprintf(buf, "%sContent-length: %d\r\n", buf, (int)strlen(content)); //filesize);
    sprintf(buf, "%sContent-type: application/json\r\n\r\n", buf);
    sprintf(buf, "%s%s", buf, content);
    printf("BUF: %s\n", buf);
    Rio_writen(fd, buf, strlen(buf));       //line:netp:servestatic:endserve
}

//Serves the /proc/meminfo stats 
void serve_meminfo(int fd, char *filename, char *cgiargs){
   
    char buf[MAXBUF];
    buf[0] = '\0';

    char content[MAXLINE];
    content[0] = '\0';
    //sprintf(content, "");

    printf("cgiargs: %s\n", cgiargs);

    if(!isCallbackValid(cgiargs)){
        sprintf(content, "Invalid arguements");
    }
    else{
        if(callbackValue(cgiargs) != NULL){

            sprintf(content, "%s(", callbackValue(cgiargs));
        }

        FILE* fp;
        char buffer[MAXBUF];
        buffer[0] = '\0';
        fp = fopen ("/proc/meminfo", "r");
        sprintf(content, "%s{", content);
        int first = 1;
        while(fgets(buffer, sizeof(buffer), fp) != NULL){
            if(!first)
                sprintf(content, "%s, ", content);  
            else
                first = 0;
            char * tok = NULL;
            tok = strtok(buffer, ": \n");
            sprintf(content, "%s\"%s\": ", content, tok);
            tok = strtok(NULL, ": \n");
            sprintf(content, "%s\"%s\"", content, tok);
        }
        sprintf(content, "%s}", content);

        fclose (fp);
    
        if(callbackValue(cgiargs) != NULL){
            sprintf(content, "%s)", content);
        }
    }

    /* Send response headers to client */
    sprintf(buf, "HTTP/1.0 200 OK\r\n");    //line:netp:servestatic:beginserve
    sprintf(buf, "%sServer: Tiny Web Server\r\n", buf);
    sprintf(buf, "%sContent-length: %d\r\n", buf, (int)strlen(content)); //filesize);
    sprintf(buf, "%sContent-type: application/json\r\n\r\n", buf);
    sprintf(buf, "%s%s", buf, content);
    printf("BUF: %s\n", buf);
    Rio_writen(fd, buf, strlen(buf));       //line:netp:servestatic:endserve
    //free(buf);
}

//isCallbackValid
int isCallbackValid(char * callback){

    printf("Callback: %s\n", callback);
    int i = 0;
    while(callback[i] != NULL){
        printf("%c\n", callback[i]);
        if(!(isalnum(callback[i])) && 
           !(callback[i] == '.' || callback[i] == '_' || 
             callback[i] == '&' || callback[i] == '=')){
            return 0;
        }
        i++;
    }

    return 1;
}

//callbackValue
//returns what the value of the callback argument is 
char * callbackValue(char * callback){
    char * tok = NULL;

    tok = strtok(callback, "&");

    printf("callback value function\n");

    while(tok != NULL){
        if(strstr(tok, "callback=") == tok){
            return strstr(tok, "=")+1;
        }
        tok = strtok(NULL, "&");
    }

   // if(!strstr(callback, "callback="))
    //    return NULL;
    return NULL;
}


/*
 * clienterror - returns an error message to the client
 */
/* $begin clienterror */
void clienterror(int fd, char *cause, char *errnum, 
		 char *shortmsg, char *longmsg) 
{
    char buf[MAXLINE], body[MAXBUF];

    /* Build the HTTP response body */
    sprintf(body, "<html><title>Tiny Error</title>");
    sprintf(body, "%s<body bgcolor=""ffffff"">\r\n", body);
    sprintf(body, "%s%s: %s\r\n", body, errnum, shortmsg);
    sprintf(body, "%s<p>%s: %s\r\n", body, longmsg, cause);
    sprintf(body, "%s<hr><em>The Tiny Web server</em>\r\n", body);

    /* Print the HTTP response */
    sprintf(buf, "HTTP/1.0 %s %s\r\n", errnum, shortmsg);
    Rio_writen(fd, buf, strlen(buf));
    sprintf(buf, "Content-type: text/html\r\n");
    Rio_writen(fd, buf, strlen(buf));
    sprintf(buf, "Content-length: %d\r\n\r\n", (int)strlen(body));
    Rio_writen(fd, buf, strlen(buf));
    Rio_writen(fd, body, strlen(body));
}
/* $end clienterror */
