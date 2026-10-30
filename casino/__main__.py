from __future__ import annotations

import argparse

from .floor import run


def main() -> None:
    argparse.ArgumentParser(
        prog="casino", description="Baddie's Casino: the casino floor, where every game starts."
    ).parse_args()
    run()


if __name__ == "__main__":
    main()
