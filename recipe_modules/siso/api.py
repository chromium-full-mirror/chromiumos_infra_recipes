# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with Siso."""

from recipe_engine import recipe_api


class SisoApi(recipe_api.RecipeApi):
  """A module for working with Siso."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._use_siso = properties.use_siso

  @property
  def use_siso(self):
    return self._use_siso
