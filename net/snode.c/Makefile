include $(TOPDIR)/rules.mk

PKG_NAME:=snode.c
PKG_VERSION:=$(or $(SNODEC_PACKAGE_VERSION),$(patsubst v%,%,$(filter v%,$(SNODEC_SOURCE_TAG))),2.0.0)
PKG_RELEASE:=$(or $(SNODEC_PACKAGE_RELEASE),1)
PKG_MIRROR_HASH:=$(or $(SNODEC_SOURCE_HASH),skip)

PKG_SOURCE:=$(PKG_NAME)-$(PKG_VERSION).tar.gz
PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/SNodeC/snode.c.git
PKG_SOURCE_VERSION:=$(or $(SNODEC_SOURCE_TAG),v$(PKG_VERSION))

PKG_MAINTAINER:=Volker Christian <me@vchrist.at>
PKG_LICENSE:=LGPL-3.0-or-later
PKG_LICENSE_FILES:=LICENSE

PKG_BUILD_DEPENDS:=nlohmannjson openssl file bluez libmariadb
PKG_BUILD_PARALLEL:=1
PKG_CONFIG_DEPENDS:=CONFIG_SNODEC_GROUP_NAME \
  CONFIG_SNODEC_EPOLL \
  CONFIG_SNODEC_POLL \
  CONFIG_SNODEC_SELECT \
  CONFIG_SNODEC_READ_BLOCKSIZE \
  CONFIG_SNODEC_WRITE_BLOCKSIZE \
  CONFIG_SNODEC_READ_TIMEOUT \
  CONFIG_SNODEC_WRITE_TIMEOUT \
  CONFIG_SNODEC_MAXIMUM_WRITE_QUEUE_BYTES \
  CONFIG_SNODEC_WRITE_QUEUE_HIGH_WATERMARK \
  CONFIG_SNODEC_WRITE_QUEUE_LOW_WATERMARK \
  CONFIG_SNODEC_BACKLOG \
  CONFIG_SNODEC_ACCEPTS_PER_TICK \
  CONFIG_SNODEC_ACCEPT_TIMEOUT \
  CONFIG_SNODEC_CONNECT_TIMEOUT \
  CONFIG_SNODEC_TERMINATE_TIMEOUT \
  CONFIG_SNODEC_RECONNECT \
  CONFIG_SNODEC_RECONNECT_TIME \
  CONFIG_SNODEC_RETRY \
  CONFIG_SNODEC_RETRY_ON_FATAL \
  CONFIG_SNODEC_RETRY_TIMEOUT \
  CONFIG_SNODEC_RETRY_TRIES \
  CONFIG_SNODEC_RETRY_BASE \
  CONFIG_SNODEC_RETRY_JITTER \
  CONFIG_SNODEC_RETRY_LIMIT \
  CONFIG_SNODEC_INV4_REUSE_ADDRESS \
  CONFIG_SNODEC_INV4_REUSE_PORT \
  CONFIG_SNODEC_INV4_DISABLE_NAGLE_ALGORITHM_TRUE \
  CONFIG_SNODEC_INV4_DISABLE_NAGLE_ALGORITHM_FALSE \
  CONFIG_SNODEC_INV4_DISABLE_NAGLE_ALGORITHM_DEFAULT \
  CONFIG_SNODEC_IPV4_NUMERIC \
  CONFIG_SNODEC_IPV4_NUMERIC_REVERSE \
  CONFIG_SNODEC_IN6_REUSE_ADDRESS \
  CONFIG_SNODEC_IN6_REUSE_PORT \
  CONFIG_SNODEC_INV6_DISABLE_NAGLE_ALGORITHM_TRUE \
  CONFIG_SNODEC_INV6_DISABLE_NAGLE_ALGORITHM_FALSE \
  CONFIG_SNODEC_INV6_DISABLE_NAGLE_ALGORITHM_DEFAULT \
  CONFIG_SNODEC_IPV6_ONLY \
  CONFIG_SNODEC_IPV4_MAPPED \
  CONFIG_SNODEC_IPV6_NUMERIC \
  CONFIG_SNODEC_IPV6_NUMERIC_REVERSE \
  CONFIG_SNODEC_TLS_INIT_TIMEOUT \
  CONFIG_SNODEC_TLS_SHUTDOWN_TIMEOUT \
  CONFIG_SNODEC_HTTP_REQUEST_PIPELINED \
  CONFIG_PACKAGE_snode.c-apps

CMAKE_INSTALL:=1

include $(INCLUDE_DIR)/package.mk
include $(INCLUDE_DIR)/cmake.mk

# FetchContent must use OpenWrt's checked download, never the network at configure time.
define Download/spdlog
  FILE:=spdlog-1.17.0.tar.gz
  URL:=https://codeload.github.com/gabime/spdlog/tar.gz/refs/tags
  URL_FILE:=v1.17.0
  HASH:=d8862955c6d74e5846b3f580b1605d2428b11d97a410d86e2fb13e857cd3a744
endef
$(eval $(call Download,spdlog))

define Build/Prepare
	$(call Build/Prepare/Default)
	$(TAR) -xzf $(DL_DIR)/spdlog-1.17.0.tar.gz -C $(PKG_BUILD_DIR)
endef

ifdef CONFIG_SNODEC_EPOLL
  CONFIG_SNODEC_IO_MULTIPLEXER=epoll
else ifdef CONFIG_SNODEC_POLL
  CONFIG_SNODEC_IO_MULTIPLEXER=poll
else ifdef CONFIG_SNODEC_SELECT
  CONFIG_SNODEC_IO_MULTIPLEXER=select
endif

ifdef CONFIG_SNODEC_INV4_DISABLE_NAGLE_ALGORITHM_TRUE
  CONFIG_SNODEC_INV4_DISABLE_NAGLE_ALGORITHM=true
else ifdef CONFIG_SNODEC_INV4_DISABLE_NAGLE_ALGORITHM_FALSE
  CONFIG_SNODEC_INV4_DISABLE_NAGLE_ALGORITHM=false
else
  CONFIG_SNODEC_INV4_DISABLE_NAGLE_ALGORITHM=default
endif

ifdef CONFIG_SNODEC_INV6_DISABLE_NAGLE_ALGORITHM_TRUE
  CONFIG_SNODEC_INV6_DISABLE_NAGLE_ALGORITHM=true
else ifdef CONFIG_SNODEC_INV6_DISABLE_NAGLE_ALGORITHM_FALSE
  CONFIG_SNODEC_INV6_DISABLE_NAGLE_ALGORITHM=false
else
  CONFIG_SNODEC_INV6_DISABLE_NAGLE_ALGORITHM=default
endif

# Reset upstream's derived cache so changed OpenWrt settings take effect.
CMAKE_OPTIONS+=-U'SNODEC_*' \
               -DCMAKE_CXX_STANDARD_LIBRARIES=-latomic \
               -DFETCHCONTENT_SOURCE_DIR_SPDLOG=$(PKG_BUILD_DIR)/spdlog-1.17.0 \
               -DFETCHCONTENT_FULLY_DISCONNECTED=ON \
               -DSPDLOG_INSTALL=OFF -DSPDLOG_SYSTEM_INCLUDES=ON \
               -DSNODEC_BUILD_APPS=$(if $(CONFIG_PACKAGE_snode.c-apps),ON,OFF) \
               -DSNODEC_BUILD_TESTS=OFF \
               -DSNODEC_CONTROL_BUILD_TUI=OFF \
               -DGROUP_NAME=$(patsubst "%",%,$(CONFIG_SNODEC_GROUP_NAME)) \
               -DIO_MULTIPLEXER=$(CONFIG_SNODEC_IO_MULTIPLEXER) \
               -DREAD_BLOCKSIZE=$(CONFIG_SNODEC_READ_BLOCKSIZE) \
               -DWRITE_BLOCKSIZE=$(CONFIG_SNODEC_WRITE_BLOCKSIZE) \
               -DREAD_TIMEOUT=$(CONFIG_SNODEC_READ_TIMEOUT) \
               -DMAXIMUM_WRITE_QUEUE_BYTES=$(CONFIG_SNODEC_MAXIMUM_WRITE_QUEUE_BYTES) \
               -DWRITE_QUEUE_HIGH_WATERMARK=$(CONFIG_SNODEC_WRITE_QUEUE_HIGH_WATERMARK) \
               -DWRITE_QUEUE_LOW_WATERMARK=$(CONFIG_SNODEC_WRITE_QUEUE_LOW_WATERMARK) \
               -DWRITE_TIMEOUT=$(CONFIG_SNODEC_WRITE_TIMEOUT) \
               -DTERMINATE_TIMEOUT=$(CONFIG_SNODEC_TERMINATE_TIMEOUT) \
               -DBACKLOG=$(CONFIG_SNODEC_BACKLOG) \
               -DACCEPTS_PER_TICK=$(CONFIG_SNODEC_ACCEPTS_PER_TICK) \
               -DIN_REUSE_ADDRESS=$(CONFIG_SNODEC_INV4_REUSE_ADDRESS) \
               -DIN_REUSE_PORT=$(CONFIG_SNODEC_INV4_REUSE_PORT) \
               -DIN_SERVER_DISABLE_NAGLE_ALGORITHM=$(CONFIG_SNODEC_INV4_DISABLE_NAGLE_ALGORITHM) \
               -DIN_CLIENT_DISABLE_NAGLE_ALGORITHM=$(CONFIG_SNODEC_INV4_DISABLE_NAGLE_ALGORITHM) \
               -DIN_NUMERIC=$(CONFIG_SNODEC_IPV4_NUMERIC) \
               -DIN_NUMERIC_REVERSE=$(CONFIG_SNODEC_IPV4_NUMERIC_REVERSE) \
               -DIN6_REUSE_ADDRESS=$(CONFIG_SNODEC_IN6_REUSE_ADDRESS) \
               -DIN6_REUSE_PORT=$(CONFIG_SNODEC_IN6_REUSE_PORT) \
               -DIN6_SERVER_DISABLE_NAGLE_ALGORITHM=$(CONFIG_SNODEC_INV6_DISABLE_NAGLE_ALGORITHM) \
               -DIN6_CLIENT_DISABLE_NAGLE_ALGORITHM=$(CONFIG_SNODEC_INV6_DISABLE_NAGLE_ALGORITHM) \
               -DIN6_IPV6_ONLY=$(if $(CONFIG_SNODEC_IPV6_ONLY),true,false) \
               -DIN6_IPV4_MAPPED=$(CONFIG_SNODEC_IPV4_MAPPED) \
               -DIN6_NUMERIC=$(CONFIG_SNODEC_IPV6_NUMERIC) \
               -DIN6_NUMERIC_REVERSE=$(CONFIG_SNODEC_IPV6_NUMERIC_REVERSE) \
               -DACCEPT_TIMEOUT=$(CONFIG_SNODEC_ACCEPT_TIMEOUT) \
               -DCONNECT_TIMEOUT=$(CONFIG_SNODEC_CONNECT_TIMEOUT) \
               -DRECONNECT=$(CONFIG_SNODEC_RECONNECT) \
               -DRECONNECT_TIME=$(CONFIG_SNODEC_RECONNECT_TIME) \
               -DRETRY=$(CONFIG_SNODEC_RETRY) \
               -DRETRY_ON_FATAL=$(CONFIG_SNODEC_RETRY_ON_FATAL) \
               -DRETRY_TIMEOUT=$(CONFIG_SNODEC_RETRY_TIMEOUT) \
               -DRETRY_TRIES=$(CONFIG_SNODEC_RETRY_TRIES) \
               -DRETRY_BASE=$(CONFIG_SNODEC_RETRY_BASE) \
               -DRETRY_JITTER=$(CONFIG_SNODEC_RETRY_JITTER) \
               -DRETRY_LIMIT=$(CONFIG_SNODEC_RETRY_LIMIT) \
               -DTLS_INIT_TIMEOUT=$(CONFIG_SNODEC_TLS_INIT_TIMEOUT) \
               -DTLS_SHUTDOWN_TIMEOUT=$(CONFIG_SNODEC_TLS_SHUTDOWN_TIMEOUT) \
               -DHTTP_REQUEST_PIPELINED=$(CONFIG_SNODEC_HTTP_REQUEST_PIPELINED) \
               -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
               -DCMAKE_SKIP_RPATH=FALSE \
               -DCHECK_INCLUDES=OFF

define Package/snode.c/Default
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=SNode.C
endef

define Package/snode.c
  $(call Package/snode.c/Default)
  TITLE:=Easy to use lightwight layer based network framework for C++
  DEPENDS:=+libstdcpp
  USERID:=$(patsubst "%",%,$(CONFIG_SNODEC_GROUP_NAME)):$(patsubst "%",%,$(CONFIG_SNODEC_GROUP_NAME))
endef

define Package/snode.c/description
  SNode.C is a very simple to use lightweight highly extendable event
driven layer-based framework for network applications in the spirit
of node.js written entirely in C++.

endef

define Package/snode.c/config
  source "$(SOURCE)/Config.in"
endef

define Package/snode.c/conffiles
/etc/snode.c/
endef

define Package/snode.c/install
	$(INSTALL_DIR) $(1)/etc/snode.c
endef

SO_VERSION=$(shell echo $(PKG_VERSION) | cut -d'.' -f1)

define BuildSNodeCModule
  define Package/snode.c-$(1)
    $$(call Package/snode.c/Default)
    TITLE:=$(1) module
    DEPENDS:=$(2)
  endef

  define Package/snode.c-$(1)/description
    This package contains the module '$(1)' of SNode.C

  endef
  
  define Package/snode.c-$(1)/install
	$(INSTALL_DIR) $$(1)$(3)
	$(CP) $(PKG_INSTALL_DIR)$(3)/libsnodec-$(1).so.$(SO_VERSION) $$(1)$(3)/
	$(CP) $(PKG_INSTALL_DIR)$(3)/libsnodec-$(1).so.$(PKG_VERSION) $$(1)$(3)/
  endef

  $$(eval $$(call BuildPackage,snode.c-$(1)))
endef

define Package/snode.c-full
  $(call Package/snode.c/Default)
  TITLE:=install all modules (no apps)
  DEPENDS:=+snode.c-core-mux-epoll \
           +snode.c-core-mux-poll \
           +snode.c-core-mux-select \
           +snode.c-net-in-stream-legacy \
           +snode.c-net-in-stream-tls \
           +snode.c-net-in6-stream-legacy \
           +snode.c-net-in6-stream-tls \
           +snode.c-net-l2-stream-legacy \
           +snode.c-net-l2-stream-tls \
           +snode.c-net-rc-stream-legacy \
           +snode.c-net-rc-stream-tls \
           +snode.c-net-un-stream-legacy \
           +snode.c-net-un-stream-tls \
           +snode.c-net-un-dgram \
           +snode.c-http-server-express \
           +snode.c-http-server-express-legacy-in \
           +snode.c-http-server-express-legacy-in6 \
           +snode.c-http-server-express-legacy-rc \
           +snode.c-http-server-express-legacy-un \
           +snode.c-http-server-express-tls-in \
           +snode.c-http-server-express-tls-in6 \
           +snode.c-http-server-express-tls-rc \
           +snode.c-http-server-express-tls-un \
           +snode.c-http-client \
           +snode.c-websocket-server \
           +snode.c-websocket-client \
           +snode.c-mqtt-server-websocket \
           +snode.c-mqtt-client-websocket \
           +snode.c-db-mariadb
endef

define Package/snode.c-full/description
 This meta-package contains dependencies for all of the SNode.C modules.
Note that the demo applications are not part of that dependency.

endef

define Package/snode.c-full/install
	true
endef

define Package/snode.c-apps
  $(call Package/snode.c/Default)
  TITLE:=SNode.C demo applications
  DEPENDS:=+snode.c-net-in-stream-legacy \
           +snode.c-net-in-stream-tls \
           +snode.c-net-in6-stream-legacy \
           +snode.c-net-in6-stream-tls \
           +snode.c-net-l2-stream-legacy \
           +snode.c-net-l2-stream-tls \
           +snode.c-net-rc-stream-legacy \
           +snode.c-net-rc-stream-tls \
           +snode.c-net-un-stream-legacy \
           +snode.c-net-un-stream-tls \
           +snode.c-http-server-express \
           +snode.c-http-client \
           +snode.c-websocket-server \
           +snode.c-websocket-client \
           +snode.c-mqtt-server \
           +snode.c-mqtt-client \
           +snode.c-db-mariadb
endef

define Package/snode.c-apps/description
 This package contains all demo applications of SNode.C.

endef

define Package/snode.c-apps/install
	$(INSTALL_DIR) $(1)/usr/bin
	find $(PKG_INSTALL_DIR)/usr/bin -mindepth 1 -maxdepth 1 ! -name snodec-control -exec $(CP) {} $(1)/usr/bin/ \;
	$(INSTALL_DIR) $(1)/usr/lib/snode.c/web/http/upgrade/websocket
	$(CP) $(PKG_INSTALL_DIR)/usr/lib/snode.c/web/http/upgrade/websocket/libsnodec-websocket-echo-server.so.$(SO_VERSION) $(1)/usr/lib/snode.c/web/http/upgrade/websocket/
	$(CP) $(PKG_INSTALL_DIR)/usr/lib/snode.c/web/http/upgrade/websocket/libsnodec-websocket-echo-server.so.$(PKG_VERSION) $(1)/usr/lib/snode.c/web/http/upgrade/websocket/
	$(CP) $(PKG_INSTALL_DIR)/usr/lib/snode.c/web/http/upgrade/websocket/libsnodec-websocket-echo-client.so.$(SO_VERSION) $(1)/usr/lib/snode.c/web/http/upgrade/websocket/
	$(CP) $(PKG_INSTALL_DIR)/usr/lib/snode.c/web/http/upgrade/websocket/libsnodec-websocket-echo-client.so.$(PKG_VERSION) $(1)/usr/lib/snode.c/web/http/upgrade/websocket/
endef

define Package/snode.c-control
  $(call Package/snode.c/Default)
  TITLE:=SNode.C control socket client
  DEPENDS:=+snode.c
endef

define Package/snode.c-control/install
	$(INSTALL_DIR) $(1)/usr/bin
	$(INSTALL_BIN) $(PKG_INSTALL_DIR)/usr/bin/snodec-control $(1)/usr/bin/
endef

$(eval $(call BuildPackage,snode.c))
$(eval $(call BuildPackage,snode.c-apps))
$(eval $(call BuildPackage,snode.c-control))
$(eval $(call BuildPackage,snode.c-full))
$(eval $(call BuildSNodeCModule,logger,+snode.c,/usr/lib))
$(eval $(call BuildSNodeCModule,utils,+snode.c-logger,/usr/lib))
$(eval $(call BuildSNodeCModule,core-mux-epoll,+snode.c-logger,/usr/lib))
$(eval $(call BuildSNodeCModule,core-mux-poll,+snode.c-logger,/usr/lib))
$(eval $(call BuildSNodeCModule,core-mux-select,+snode.c-logger,/usr/lib))
$(eval $(call BuildSNodeCModule,core,+snode.c-utils +libatomic +SNODEC_EPOLL:snode.c-core-mux-epoll +SNODEC_POLL:snode.c-core-mux-poll +SNODEC_SELECT:snode.c-core-mux-select,/usr/lib))
$(eval $(call BuildSNodeCModule,core-socket,+snode.c-core,/usr/lib))
$(eval $(call BuildSNodeCModule,core-socket-stream,+snode.c-core-socket,/usr/lib))
$(eval $(call BuildSNodeCModule,core-socket-stream-legacy,+snode.c-core-socket-stream,/usr/lib))
$(eval $(call BuildSNodeCModule,core-socket-stream-tls,+snode.c-core-socket-stream +libopenssl,/usr/lib))
$(eval $(call BuildSNodeCModule,db-mariadb,+snode.c-core +libmariadb,/usr/lib))
$(eval $(call BuildSNodeCModule,net,+snode.c-core-socket,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in,+snode.c-net,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in-phy,+snode.c-net-in,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in-phy-stream,+snode.c-net-in-phy,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in-stream,+snode.c-net-in-phy-stream,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in-stream-legacy,+snode.c-net-in-stream +snode.c-core-socket-stream-legacy,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in-stream-tls,+snode.c-net-in-stream +snode.c-core-socket-stream-tls,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in6,+snode.c-net,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in6-phy,+snode.c-net-in6,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in6-phy-stream,+snode.c-net-in6-phy,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in6-stream,+snode.c-net-in6-phy-stream,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in6-stream-legacy,+snode.c-net-in6-stream +snode.c-core-socket-stream-legacy,/usr/lib))
$(eval $(call BuildSNodeCModule,net-in6-stream-tls,+snode.c-net-in6-stream +snode.c-core-socket-stream-tls,/usr/lib))
$(eval $(call BuildSNodeCModule,net-l2,+snode.c-net +bluez-libs,/usr/lib))
$(eval $(call BuildSNodeCModule,net-l2-phy,+snode.c-net-l2 +bluez-libs,/usr/lib))
$(eval $(call BuildSNodeCModule,net-l2-phy-stream,+snode.c-net-l2-phy,/usr/lib))
$(eval $(call BuildSNodeCModule,net-l2-stream,+snode.c-net-l2-phy-stream,/usr/lib))
$(eval $(call BuildSNodeCModule,net-l2-stream-legacy,+snode.c-net-l2-stream +snode.c-core-socket-stream-legacy,/usr/lib))
$(eval $(call BuildSNodeCModule,net-l2-stream-tls,+snode.c-net-l2-stream +snode.c-core-socket-stream-tls,/usr/lib))
$(eval $(call BuildSNodeCModule,net-rc,+snode.c-net +bluez-libs,/usr/lib))
$(eval $(call BuildSNodeCModule,net-rc-phy,+snode.c-net-rc +bluez-libs,/usr/lib))
$(eval $(call BuildSNodeCModule,net-rc-phy-stream,+snode.c-net-rc-phy,/usr/lib))
$(eval $(call BuildSNodeCModule,net-rc-stream,+snode.c-net-rc-phy-stream,/usr/lib))
$(eval $(call BuildSNodeCModule,net-rc-stream-legacy,+snode.c-net-rc-stream +snode.c-core-socket-stream-legacy,/usr/lib))
$(eval $(call BuildSNodeCModule,net-rc-stream-tls,+snode.c-net-rc-stream +snode.c-core-socket-stream-tls,/usr/lib))
$(eval $(call BuildSNodeCModule,net-un,+snode.c-net,/usr/lib))
$(eval $(call BuildSNodeCModule,net-un-phy,+snode.c-net-un,/usr/lib))
$(eval $(call BuildSNodeCModule,net-un-phy-stream,+snode.c-net-un-phy,/usr/lib))
$(eval $(call BuildSNodeCModule,net-un-stream,+snode.c-net-un-phy-stream,/usr/lib))
$(eval $(call BuildSNodeCModule,net-un-stream-legacy,+snode.c-net-un-stream +snode.c-core-socket-stream-legacy,/usr/lib))
$(eval $(call BuildSNodeCModule,net-un-stream-tls,+snode.c-net-un-stream +snode.c-core-socket-stream-tls,/usr/lib))
$(eval $(call BuildSNodeCModule,net-un-dgram,+snode.c-net-un-phy +snode.c-net-un,/usr/lib))
$(eval $(call BuildSNodeCModule,http,+snode.c-core-socket-stream +libmagic,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-server,+snode.c-http,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-client,+snode.c-http,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-server-express,+snode.c-http-server,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-server-express-legacy-in,+snode.c-http-server-express +snode.c-net-in-stream-legacy,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-server-express-legacy-in6,+snode.c-http-server-express +snode.c-net-in6-stream-legacy,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-server-express-legacy-rc,+snode.c-http-server-express +snode.c-net-rc-stream-legacy,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-server-express-legacy-un,+snode.c-http-server-express +snode.c-net-un-stream-legacy,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-server-express-tls-in,+snode.c-http-server +snode.c-http-server-express +snode.c-net-in-stream-tls,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-server-express-tls-in6,+snode.c-http-server +snode.c-http-server-express +snode.c-net-in6-stream-tls,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-server-express-tls-rc,+snode.c-http-server +snode.c-http-server-express +snode.c-net-rc-stream-tls,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,http-server-express-tls-un,+snode.c-http-server +snode.c-http-server-express +snode.c-net-un-stream-tls,/usr/lib/snode.c/web/http))
$(eval $(call BuildSNodeCModule,websocket,+snode.c-utils,/usr/lib/snode.c/web/http/upgrade))
$(eval $(call BuildSNodeCModule,websocket-server,+snode.c-websocket +snode.c-http-server,/usr/lib/snode.c/web/http/upgrade))
$(eval $(call BuildSNodeCModule,websocket-client,+snode.c-websocket +snode.c-http-client,/usr/lib/snode.c/web/http/upgrade))
$(eval $(call BuildSNodeCModule,mqtt,+snode.c-core-socket-stream,/usr/lib/snode.c/iot/mqtt))
$(eval $(call BuildSNodeCModule,mqtt-server,+snode.c-mqtt,/usr/lib/snode.c/iot/mqtt))
$(eval $(call BuildSNodeCModule,mqtt-client,+snode.c-mqtt,/usr/lib/snode.c/iot/mqtt))
$(eval $(call BuildSNodeCModule,mqtt-server-websocket,+snode.c-mqtt-server +snode.c-websocket-server,/usr/lib/snode.c/iot/mqtt))
$(eval $(call BuildSNodeCModule,mqtt-client-websocket,+snode.c-mqtt-client +snode.c-websocket-client,/usr/lib/snode.c/iot/mqtt))
