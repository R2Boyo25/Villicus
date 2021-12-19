import sys

binf = sys.argv[1]
filesFolder = sys.argv[2]

with open(binf, 'w') as f:
    f.write(f'#!/bin/bash\ncd "{filesFolder}"\n"python3 "{filesFolder}/main.py" "$@"')