/**
 * threadpool.c
 */
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <pthread.h>
#include <semaphore.h>
#include "list.h"
#include "threadpool.h"

struct thread_pool {
    bool shutdown;
    int numThreads;

    // Array of threads
    pthread_t * threadArray;    

    // List of futures  
    struct list futureList;     

    pthread_cond_t cond;    
    pthread_mutex_t mutex;
};

struct future {
    void * data;
    void * result;

    thread_pool_callable_func_t futureFunction;
    
    // Semaphores are counters for resources shared between
    // threads. Then basic operations on semaphores are: increment
    // the counter atomically, and wait until the counter is non-
    // null and decrement it atomically.
    sem_t sem;
    
    struct list_elem elem;
};

static void * threadFunction(void * tPool) {
    //printf("%s\n", "thread function");

    struct thread_pool * threadPool = (struct thread_pool *)tPool;

    // To make sure the thread that holds the mutex doesn't do lock more than 1 time
    bool lock = false;
    
    while (true) {  
        if (threadPool->shutdown) {
            pthread_mutex_unlock(&threadPool->mutex);
            
            // Causes the current thread to exit and free any thread-specific 
            // resources it is taking. 
            pthread_exit(NULL); 
        }

        // Once some thread gets the lock, no other threads can go over this if statement.
        if (!lock) {
            pthread_mutex_lock(&threadPool->mutex);
            lock = true;            
        }

        if (list_empty(&threadPool->futureList)) {
            // Spurious wakeups may occur (It may stop waiting for no reasons)            
            pthread_cond_wait(&threadPool->cond, &threadPool->mutex); 
        }
        else {
            // Take an element out of the list of futures and execute it
            struct future * aFuture = list_entry(list_pop_front(&threadPool->futureList), struct future, elem);

            pthread_mutex_unlock(&threadPool->mutex);  
            lock = false;

            aFuture->result = (*(aFuture->futureFunction))(aFuture->data);            
            sem_post(&aFuture->sem);    
        } 
    }

    return NULL;
}

struct thread_pool * thread_pool_new(int nthreads) {
    struct thread_pool * threadPool = (struct thread_pool *) malloc(sizeof(struct thread_pool));

    /*---------------- Initialize a list of futures --------------------*/
    list_init(&threadPool->futureList);

    /*---------------- Set things up for the pool of threads -------------*/
    threadPool->shutdown = false;
    threadPool->cond = (pthread_cond_t)PTHREAD_COND_INITIALIZER; 
    threadPool->mutex = (pthread_mutex_t)PTHREAD_MUTEX_INITIALIZER;

    // Initialize an array of threads and create them
    int i;
    threadPool->threadArray = (pthread_t *)malloc(nthreads * sizeof(pthread_t));
    for (i = 0; i < nthreads; ++i) {
        pthread_create(&threadPool->threadArray[i], NULL, threadFunction, (void *) threadPool);
    }
    threadPool->numThreads = nthreads;   

    return threadPool;
}

struct future * thread_pool_submit(struct thread_pool * threadPool, thread_pool_callable_func_t callableFunction, void * callableData) {
    //printf("%s\n", "submit");

    pthread_mutex_lock(&threadPool->mutex);

    // Creat a new future and put it to the list
    struct future * aFuture = (struct future *)malloc(sizeof(struct future));
    aFuture->data = callableData;
    aFuture->futureFunction = callableFunction;
    list_push_back(&threadPool->futureList, &aFuture->elem);
    
    sem_init(&aFuture->sem, 0, 0);

    // Send a signal to the pthread_cond_wait() in the threadpooFunction()
    // 
    // The pthread_cond_signal() routine is used to signal (or wake up) 
    // another thread which is waiting on the condition variable. 
    // It should be called after mutex is locked, and must unlock mutex 
    // in order for pthread_cond_wait() routine to complete. 
    pthread_cond_signal(&threadPool->cond);
            
    pthread_mutex_unlock(&threadPool->mutex);

    return aFuture;
}

void thread_pool_shutdown(struct thread_pool * threadPool) {
    //printf("%s\n", "shutdown");

    pthread_mutex_lock(&threadPool->mutex);

    threadPool->shutdown = 1;

    // pthread_cond_broadcast: wake up all threads blocked by the specified 
    // condition variable.
    // 
    // (Wake all of them up, after that join them and kill them)
    pthread_cond_broadcast(&threadPool->cond);
    
    pthread_mutex_unlock(&threadPool->mutex);
    
    // Joins the threads together (basically kill them)
    //
    // A call to pthread_join blocks the calling thread until the thread with 
    // identifier equal to the first argument terminates. 
    int i;
    for (i = 0; i < threadPool->numThreads; ++i) {
        pthread_join(threadPool->threadArray[i], NULL); 
    }
   
    pthread_cond_destroy(&threadPool->cond);
    pthread_mutex_destroy(&threadPool->mutex);

    free(threadPool);
}

void * future_get(struct future * aFuture) {
    // sem_wait suspends the calling thread until the semaphore
    // pointed to by sem has non-zero count. It then atomically
    // decreases the semaphore count.
    sem_wait(&aFuture->sem);
    
    return aFuture->result;
}

void future_free(struct future * aFuture) {
    free(aFuture);
}

// Some notes:
// The pthread_cond_broadcast() or pthread_cond_signal() functions may be called 
// by a thread whether or not it currently owns the mutex that threads calling 
// pthread_cond_wait() or pthread_cond_timedwait() have associated with the 
// condition variable during their waits; however, if predictable scheduling 
// behavior is required, then that mutex shall be locked by the thread calling 
// pthread_cond_broadcast() or pthread_cond_signal().
//
// Link: http://stackoverflow.com/questions/4544234/calling-pthread-cond-signal-without-locking-mutex