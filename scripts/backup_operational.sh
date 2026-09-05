#!/bin/sh
set -eu

destination=${1:?usage: backup_operational.sh DESTINATION SECRET_FILE EXPORT_ZIP}
secret_file=${2:?usage: backup_operational.sh DESTINATION SECRET_FILE EXPORT_ZIP}
export_zip=${3:?usage: backup_operational.sh DESTINATION SECRET_FILE EXPORT_ZIP}
[ -r "$secret_file" ] || { echo "secret file is not readable" >&2; exit 2; }
[ -r "$export_zip" ] || { echo "export ZIP is not readable" >&2; exit 2; }
mkdir -p "$destination"
umask 077
output="$destination/galaxz-$(date -u +%Y%m%dT%H%M%SZ).zip.enc"
openssl enc -aes-256-cbc -pbkdf2 -salt -in "$export_zip" -out "$output" -pass "file:$secret_file"
ln -sfn "$(basename "$output")" "$destination/latest.zip.enc"
check=$(mktemp "$destination/.backup-check.XXXXXX.zip")
trap 'rm -f "$check"' EXIT
openssl enc -d -aes-256-cbc -pbkdf2 -in "$output" -out "$check" -pass "file:$secret_file"
unzip -t -q "$check" || { echo "backup verification failed" >&2; exit 1; }
echo "$output"
