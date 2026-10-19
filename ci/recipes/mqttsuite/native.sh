#!/usr/bin/env bash
cmake -S sources/mqttsuite -B build-product -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_INSTALL_LIBDIR="$libdir" -DCMAKE_INSTALL_SYSCONFDIR=/etc
cmake --build build-product --parallel 4
package build-product
