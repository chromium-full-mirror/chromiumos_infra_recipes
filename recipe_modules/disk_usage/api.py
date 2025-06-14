# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib

from recipe_engine import recipe_api


class DiskUsageApi(recipe_api.RecipeApi):
  """A module to process tast-results/ directory."""

  @contextlib.contextmanager
  def tracking_context(self):
    """A context wrapper for track()."""
    try:
      self.track('initial disk usage', depth=0)
      yield
    finally:
      self.track('final disk usage', depth=2)

  def track(self, step_name=None, depth=0, timeout=10 * 60, d=None):
    """Print out the disk usage under the current directory.

    Args:
      depth (int): The depth to traverse within the subdirs.
      timeout (int): timeout in seconds.
      d (str): absolute dir path to start from. If empty, use cwd.
    """
    args = ['--depth', str(depth)]
    if d:
      args += ['--dir', d]
    self.m.step((step_name or 'track disk usage'),
                ['vpython3', self.resource('track_disk_usage.py')] + args,
                timeout=timeout, ok_ret='any')
