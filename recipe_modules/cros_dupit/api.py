# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for DupIt script."""

from recipe_engine import recipe_api


class DupItApi(recipe_api.RecipeApi):
  """A module for the DupIt script."""

  def __init__(self, *args, **kwargs):
    super(DupItApi, self).__init__(*args, **kwargs)
    self._dryrun = False

  def configure(self, dryrun=None):
    """Configure the DupIt script module.

    Args:
      * dryrun (bool): If True, run gsutil updates in a dryrun mode.
    """
    if dryrun is not None:
      self._dryrun = dryrun

  def run(self):
    self.m.python('run dupit.py', self.resource('dupit.py'),
                  args=['--dryrun=%s' % self.dryrun])

  @property
  def dryrun(self):
    return self._dryrun
