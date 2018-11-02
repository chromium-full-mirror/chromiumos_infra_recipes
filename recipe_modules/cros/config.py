# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine.config import config_item_context, ConfigGroup, Dict, Static
from recipe_engine.config_types import Path


def BaseConfig(MASTER_SRC_PATH, WORKSPACE_SRC_PATH, CHROOT_PATH, **_kwargs):
  return ConfigGroup(
      MASTER_SRC_PATH=Static(MASTER_SRC_PATH),
      WORKSPACE_SRC_PATH=Static(WORKSPACE_SRC_PATH),
      CHROOT_PATH=Static(CHROOT_PATH),
  )


config_ctx = config_item_context(BaseConfig)
