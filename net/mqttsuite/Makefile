include $(TOPDIR)/rules.mk

PKG_NAME:=mqttsuite
PKG_VERSION:=$(or $(MQTTSUITE_PACKAGE_VERSION),$(patsubst v%,%,$(filter v%,$(MQTTSUITE_SOURCE_TAG))),1.0.2)
PKG_RELEASE:=$(or $(MQTTSUITE_PACKAGE_RELEASE),1)
PKG_MIRROR_HASH:=$(or $(MQTTSUITE_SOURCE_HASH),skip)
PKG_SOURCE:=$(PKG_NAME)-$(PKG_VERSION).tar.gz
PKG_SOURCE_PROTO:=git
PKG_SOURCE_URL:=https://github.com/SNodeC/mqttsuite.git
PKG_SOURCE_VERSION:=$(or $(MQTTSUITE_SOURCE_TAG),v$(PKG_VERSION))
PKG_MAINTAINER:=Volker Christian <me@vchrist.at>
PKG_LICENSE:=GPL-3.0-or-later
PKG_LICENSE_FILES:=LICENSE
PKG_BUILD_DEPENDS:=nlohmannjson snode.c
PKG_BUILD_PARALLEL:=1

MQTTSUITE_APPS:=broker integrator bridge cli store
MQTTSUITE_TRANSPORTS:=TCP_IPV4 TLS_IPV4 TCP_IPV6 TLS_IPV6 UNIX UNIX_TLS WS WSS
PKG_CONFIG_DEPENDS:=$(foreach app,$(MQTTSUITE_APPS),CONFIG_PACKAGE_mqttsuite-$(app)) \
  $(foreach app,BROKER INTEGRATOR BRIDGE CLI STORE,$(foreach transport,$(MQTTSUITE_TRANSPORTS),CONFIG_MQTTSUITE_$(app)_$(transport)))
# In-source builds let lib/Log.h shadow SNode.C's public Log.h.
CMAKE_BINARY_SUBDIR:=openwrt-build
CMAKE_INSTALL:=1

include $(INCLUDE_DIR)/package.mk
include $(INCLUDE_DIR)/cmake.mk

CMAKE_OPTIONS += -DCMAKE_SKIP_RPATH=FALSE -DCMAKE_MODULE_PATH=$(CURDIR)/files
CMAKE_OPTIONS += $(foreach app,BROKER INTEGRATOR BRIDGE CLI STORE,$(foreach transport,$(MQTTSUITE_TRANSPORTS),-DCONFIG_MQTTSUITE_$(app)_$(transport)=$(if $(CONFIG_MQTTSUITE_$(app)_$(transport)),ON,OFF)))

define Package/mqttsuite/Default
  SECTION:=net
  CATEGORY:=Network
  SUBMENU:=MQTTSuite
  URL:=https://github.com/SNodeC/mqttsuite
endef

define Package/mqttsuite
  $(call Package/mqttsuite/Default)
  TITLE:=MQTTSuite configuration and application base
endef

define Package/mqttsuite/config
  source "$(SOURCE)/Config.in"
endef

define Package/mqttsuite/install
	true
endef

# Dependency conditions must survive DUMP=1, where .config is not loaded.

define Package/mqttsuite-broker
  $(call Package/mqttsuite/Default)
  TITLE:=MQTT broker
  DEPENDS:=+mqttsuite \
    +snode.c-mqtt-server \
    +MQTTSUITE_BROKER_TCP_IPV4:snode.c-net-in-stream-legacy \
    +MQTTSUITE_BROKER_TCP_IPV4:snode.c-http-server-express-legacy-in \
    +MQTTSUITE_BROKER_TLS_IPV4:snode.c-net-in-stream-tls \
    +MQTTSUITE_BROKER_TLS_IPV4:snode.c-http-server-express-tls-in \
    +MQTTSUITE_BROKER_TCP_IPV6:snode.c-net-in6-stream-legacy \
    +MQTTSUITE_BROKER_TCP_IPV6:snode.c-http-server-express-legacy-in6 \
    +MQTTSUITE_BROKER_TLS_IPV6:snode.c-net-in6-stream-tls \
    +MQTTSUITE_BROKER_TLS_IPV6:snode.c-http-server-express-tls-in6 \
    +MQTTSUITE_BROKER_UNIX:snode.c-net-un-stream-legacy \
    +MQTTSUITE_BROKER_UNIX:snode.c-http-server-express-legacy-un \
    +MQTTSUITE_BROKER_UNIX_TLS:snode.c-net-un-stream-tls \
    +MQTTSUITE_BROKER_UNIX_TLS:snode.c-http-server-express-tls-un \
    +MQTTSUITE_BROKER_WS:snode.c-mqtt-server-websocket \
    +MQTTSUITE_BROKER_WSS:snode.c-mqtt-server-websocket
endef

define Package/mqttsuite-integrator
  $(call Package/mqttsuite/Default)
  TITLE:=MQTT integrator
  DEPENDS:=+mqttsuite \
    +snode.c-mqtt-client \
    +snode.c-http-server-express-legacy-in \
    +snode.c-http-server-express-tls-in \
    +MQTTSUITE_INTEGRATOR_TCP_IPV4:snode.c-net-in-stream-legacy \
    +MQTTSUITE_INTEGRATOR_TLS_IPV4:snode.c-net-in-stream-tls \
    +MQTTSUITE_INTEGRATOR_TCP_IPV6:snode.c-net-in6-stream-legacy \
    +MQTTSUITE_INTEGRATOR_TLS_IPV6:snode.c-net-in6-stream-tls \
    +MQTTSUITE_INTEGRATOR_UNIX:snode.c-net-un-stream-legacy \
    +MQTTSUITE_INTEGRATOR_UNIX_TLS:snode.c-net-un-stream-tls \
    +MQTTSUITE_INTEGRATOR_WS:snode.c-mqtt-client-websocket \
    +MQTTSUITE_INTEGRATOR_WSS:snode.c-mqtt-client-websocket
endef

define Package/mqttsuite-bridge
  $(call Package/mqttsuite/Default)
  TITLE:=MQTT bridge
  DEPENDS:=+mqttsuite \
    +snode.c-mqtt-client \
    +snode.c-http-server-express-legacy-in \
    +snode.c-http-server-express-tls-in \
    +MQTTSUITE_BRIDGE_TCP_IPV4:snode.c-net-in-stream-legacy \
    +MQTTSUITE_BRIDGE_TLS_IPV4:snode.c-net-in-stream-tls \
    +MQTTSUITE_BRIDGE_TCP_IPV6:snode.c-net-in6-stream-legacy \
    +MQTTSUITE_BRIDGE_TLS_IPV6:snode.c-net-in6-stream-tls \
    +MQTTSUITE_BRIDGE_UNIX:snode.c-net-un-stream-legacy \
    +MQTTSUITE_BRIDGE_UNIX_TLS:snode.c-net-un-stream-tls \
    +MQTTSUITE_BRIDGE_WS:snode.c-mqtt-client-websocket \
    +MQTTSUITE_BRIDGE_WSS:snode.c-mqtt-client-websocket
endef

define Package/mqttsuite-cli
  $(call Package/mqttsuite/Default)
  TITLE:=MQTT cli
  DEPENDS:=+mqttsuite \
    +snode.c-mqtt-client \
    +MQTTSUITE_CLI_TCP_IPV4:snode.c-net-in-stream-legacy \
    +MQTTSUITE_CLI_TLS_IPV4:snode.c-net-in-stream-tls \
    +MQTTSUITE_CLI_TCP_IPV6:snode.c-net-in6-stream-legacy \
    +MQTTSUITE_CLI_TLS_IPV6:snode.c-net-in6-stream-tls \
    +MQTTSUITE_CLI_UNIX:snode.c-net-un-stream-legacy \
    +MQTTSUITE_CLI_UNIX_TLS:snode.c-net-un-stream-tls \
    +MQTTSUITE_CLI_WS:snode.c-mqtt-client-websocket \
    +MQTTSUITE_CLI_WSS:snode.c-mqtt-client-websocket
endef

define Package/mqttsuite-store
  $(call Package/mqttsuite/Default)
  TITLE:=MQTT store
  DEPENDS:=+mqttsuite \
    +snode.c-mqtt-client \
    +snode.c-db-mariadb \
    +MQTTSUITE_STORE_TCP_IPV4:snode.c-net-in-stream-legacy \
    +MQTTSUITE_STORE_TLS_IPV4:snode.c-net-in-stream-tls \
    +MQTTSUITE_STORE_TCP_IPV6:snode.c-net-in6-stream-legacy \
    +MQTTSUITE_STORE_TLS_IPV6:snode.c-net-in6-stream-tls \
    +MQTTSUITE_STORE_UNIX:snode.c-net-un-stream-legacy \
    +MQTTSUITE_STORE_UNIX_TLS:snode.c-net-un-stream-tls \
    +MQTTSUITE_STORE_WS:snode.c-mqtt-client-websocket \
    +MQTTSUITE_STORE_WSS:snode.c-mqtt-client-websocket
endef

# Install a plugin only when its transport is compiled. Keep ABI symlinks;
# SNode.C's loader uses .so.2 although MQTTSuite's file version is 1.0.1.
define Package/mqttsuite/install-app
	$(INSTALL_DIR) $(1)/usr/bin $(1)/usr/lib
	$(CP) $(PKG_INSTALL_DIR)/usr/bin/mqtt$(2) $(1)/usr/bin/
	$(CP) $(PKG_INSTALL_DIR)/usr/lib/libmqtt-$(2).so.* $(1)/usr/lib/
	$(if $(CONFIG_MQTTSUITE_$(3)_WS),$(INSTALL_DIR) $(1)/usr/lib/snode.c/web/http/upgrade/websocket/mqtt$(2))
	$(if $(CONFIG_MQTTSUITE_$(3)_WS),$(CP) $(PKG_INSTALL_DIR)/usr/lib/snode.c/web/http/upgrade/websocket/mqtt$(2)/*.so.* $(1)/usr/lib/snode.c/web/http/upgrade/websocket/mqtt$(2)/)
	$(if $(filter broker bridge,$(2)),$(INSTALL_DIR) $(1)/usr/var/www/mqttsuite/mqtt$(2))
	$(if $(filter broker bridge,$(2)),$(CP) $(PKG_INSTALL_DIR)/usr/var/www/mqttsuite/mqtt$(2)/* $(1)/usr/var/www/mqttsuite/mqtt$(2)/)
	$(if $(filter broker integrator bridge,$(2)),$(INSTALL_DIR) $(1)/etc/init.d)
	$(if $(filter broker integrator bridge,$(2)),$(INSTALL_BIN) ./files/mqtt$(2).init $(1)/etc/init.d/mqtt$(2))
	bash ./files/normalize-rpath.sh "$(STAGING_DIR_HOST)/bin/patchelf" "$(TARGET_CROSS)readelf" "$(STAGING_DIR)" "$(1)/usr"
endef

define Package/mqttsuite-broker/install
	$(call Package/mqttsuite/install-app,$(1),broker,BROKER)
endef

define Package/mqttsuite-integrator/install
	$(call Package/mqttsuite/install-app,$(1),integrator,INTEGRATOR)
endef

define Package/mqttsuite-bridge/install
	$(call Package/mqttsuite/install-app,$(1),bridge,BRIDGE)
endef

define Package/mqttsuite-cli/install
	$(call Package/mqttsuite/install-app,$(1),cli,CLI)
endef

define Package/mqttsuite-store/install
	$(call Package/mqttsuite/install-app,$(1),store,STORE)
endef

define MQTTSuiteMappingPlugin
  define Package/mqttsuite-mapping-$(1)
    $$(call Package/mqttsuite/Default)
    TITLE:=MQTT mapping plugin: $(1)
    DEPENDS:=+mqttsuite +libstdcpp
  endef
  define Package/mqttsuite-mapping-$(1)/install
	$$(INSTALL_DIR) $$(1)/usr/lib
	$$(CP) $$(PKG_INSTALL_DIR)/usr/lib/libmqtt-mapping-plugin-$(1).so $$(1)/usr/lib/
	bash ./files/normalize-rpath.sh "$$(STAGING_DIR_HOST)/bin/patchelf" "$$(TARGET_CROSS)readelf" "$$(STAGING_DIR)" "$$(1)/usr"
  endef
  $$(eval $$(call BuildPackage,mqttsuite-mapping-$(1)))
endef

define Package/mqttsuite-full
  $(call Package/mqttsuite/Default)
  TITLE:=All MQTTSuite applications and mapping plugins
  DEPENDS:=$(foreach app,$(MQTTSUITE_APPS),+mqttsuite-$(app)) +mqttsuite-mapping-double +mqttsuite-mapping-storage
endef

define Package/mqttsuite-full/install
	true
endef

$(eval $(call BuildPackage,mqttsuite))
$(foreach app,$(MQTTSUITE_APPS),$(eval $(call BuildPackage,mqttsuite-$(app))))
$(eval $(call MQTTSuiteMappingPlugin,double))
$(eval $(call MQTTSuiteMappingPlugin,storage))
$(eval $(call BuildPackage,mqttsuite-full))
