"""The default view of `relay queue`: the ordered table. A queue extension reads items and prints; it never writes them."""

import relay_queue


def run(items, args):
    for line in relay_queue.list_lines(items, header=True) or ["the queue is empty"]:
        print(line)
    return 0
