# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Sysroot archive functions."""

from recipe_engine import recipe_api
from PB.recipe_modules.chromeos.sysroot_archive.sysroot_archive import SysrootArchiveApiProperties


class SysrootArchiveApi(recipe_api.RecipeApi):
  """A module for interacting with sysroot archive."""

  def __init__(self, props: SysrootArchiveApiProperties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.sysroot_enabled = props.sysroot_enabled
