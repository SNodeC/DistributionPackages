#!/bin/sh
# Keep detection and repository setup in the shared installer.
exec sh "$(dirname "$0")/install.sh" --project snodec-idp "$@"
