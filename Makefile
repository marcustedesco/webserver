CC = gcc
CFLAGS = -O2 -Wall -I .

# This flag includes the Pthreads library on a Linux box.
# Others systems will probably require something different.
LIB = -lpthread

all: sysstatd cgi

sysstatd: tiny.c csapp.o
	$(CC) $(CFLAGS) -o sysstatd tiny.c csapp.o $(LIB)

csapp.o:
	$(CC) $(CFLAGS) -c csapp.c

cgi:
	(cd cgi-bin; make)

clean:
	rm -f *.o sysstatd *~
	(cd cgi-bin; make clean)

