"""
Example target process to be debugged, for demos or testing.
"""

import time
import os
import sys
import math
from collections import defaultdict
import random


def _is_prime(n: int):
    for k in range(2, min(n, math.ceil(n**0.5) + 1)):
        if not (n % k):
            return False
    return True


PRIME_SEARCH_CAP = 1 * 10**6
PRIMES_LIST = [n for n in range(2, PRIME_SEARCH_CAP) if _is_prime(n)]


def factorize(n):
    if n in {0, 1}:
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


def work_loop(delay=0.1):
    """Simulate some work being done."""
    counter = 0
    while True:
        counter += 1
        n = random.randint(10**5, PRIME_SEARCH_CAP)
        result = factorize(n)
        print(f"Iteration {counter}, number {n}, factors: {result}")

        time.sleep(delay)


def main():
    """Main entry point for the target process."""
    delay = float(sys.argv[1]) if len(sys.argv) > 1 else 0.1

    print("Starting work loop...", flush=True)

    try:
        work_loop(delay)
    except KeyboardInterrupt:
        print("\nTarget process interrupted", flush=True)
    except Exception as e:
        print(f"Error in target process: {e}", file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
