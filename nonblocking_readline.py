import sys
import select

def nonblocking_readline():
    # If there's input ready, return one line
    # else return None
    #Note timeout is zero so select won't block at all.
    if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
        return  sys.stdin.readline()
    else:
       return None
