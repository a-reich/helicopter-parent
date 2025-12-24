"""
target.py - Script B: The target process to be debugged

This is a simple example script that runs in the background.
It can be replaced with any Python script/application.
"""

import time
import os
import sys
import math
from collections import defaultdict
import logging
import random

logger = logging.getLogger(__name__)

def _is_prime(n: int):
    for k in range(2, min(n, math.ceil(n**0.5)+1)):
        if not (n % k):
            return False
    return True

PRIME_SEARCH_CAP = 1 * 10**6
PRIMES_LIST = [n for n in range(2, PRIME_SEARCH_CAP) if _is_prime(n)]
def factorize(n):
    if n in {0,1}:
        return {}
    assert n <= PRIMES_LIST[-1]
    reduced = n
    exponents = defaultdict(lambda: 0)
    for p in PRIMES_LIST:
        while reduced % p == 0:
            reduced = reduced // p
            exponents[p] += 1
        if reduced == 1:
            break
    return dict(exponents)

def work_loop():
    """Simulate some work being done."""
    counter = 0
    while True:
        counter += 1
        n = random.randint(10**5, PRIME_SEARCH_CAP)
        result = factorize(n)
        logger.info(f"Iteration {counter}, number {n}")

        time.sleep(0.1)


def main():
    """Main entry point for the target process."""
    print(f"Target process started (PID: {os.getpid()})", flush=True)
    print("Starting work loop...", flush=True)

    try:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s:%(message)s')
        work_loop()
    except KeyboardInterrupt:
        print("\nTarget process interrupted", flush=True)
    except Exception as e:
        print(f"Error in target process: {e}", file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
