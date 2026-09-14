"""Rebuild current authored episodes, retaining old artifacts for comparison."""
import argparse
from pathlib import Path
from .pilots import build

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path('outputs/pilots-v3'))
    parser.add_argument('--source-root',type=Path,default=Path('outputs/credible'))
    args=parser.parse_args()
    build(args.output,args.source_root)

if __name__=='__main__': main()
