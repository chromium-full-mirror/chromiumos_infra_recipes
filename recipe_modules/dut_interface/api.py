# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import recipe_api
from . import phosphorus_interface, crostoolrunner_interface


class DUTInterface(recipe_api.RecipeApi):

  def create(self, api, properties):
    """Factory constructor for interfaces.

    Args:
    * api (RecipeScriptApi): Ubiquitous recipe API
    * properties (TestRunnerProperties): Input recipe properties.

    Returns:
      DUTInterface
    """
    if properties.cft_mvp_is_enabled:
      return crostoolrunner_interface.CrosToolRunnerInterface(api, properties)
    else:
      return phosphorus_interface.PhosphorusInterface(api, properties)
