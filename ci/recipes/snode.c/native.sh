#!/usr/bin/env bash
cmake -S sources/snode.c -B build-snodec -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_INSTALL_LIBDIR="$libdir" -DCMAKE_INSTALL_SYSCONFDIR=/etc \
    -DSNODEC_BUILD_TESTS=ON -DSNODEC_BUILD_APPS=ON \
    -DSPDLOG_SYSTEM_INCLUDES=ON
cmake --build build-snodec --parallel 4
package build-snodec
install_packages /work/packages/*."${format,,}"
chown -R snodec-test:snodec-test build-snodec
runuser -u snodec-test -- ctest --test-dir build-snodec --output-on-failure
