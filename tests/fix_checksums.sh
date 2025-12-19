#!/bin/bash
# Fix existing sample files to have unique random checksums

cd "$(dirname "$0")/sample_grub_configs" || exit 1

for f in 29991213-000000-00000000.*.bak; do
    if [ -f "$f" ]; then
        # Generate random checksum
        checksum=$(echo "$f-$RANDOM" | md5sum | cut -c1-8 | tr '[:lower:]' '[:upper:]')
        # Create new name
        newname=$(echo "$f" | sed "s/00000000/$checksum/")
        echo "Renaming: $f -> $newname"
        mv "$f" "$newname"
    fi
done

echo "Done! Files now:"
ls -1 *.bak
