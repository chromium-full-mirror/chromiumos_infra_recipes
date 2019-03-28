# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for testing cros_prebuilts API."""

from recipe_engine import recipe_test_api


class CrosPrebuiltsTestApi(recipe_test_api.RecipeTestApi):
  """Fake data for cros_prebuilts tests."""

  @property
  def prepare_binhost_uploads_response(self):
    """Returns a fake PrepareBinhostUploadsResponse as a dict."""
    uploads_dir = str(self.m.path['start_dir'].join('uploads/dir'))
    return """\
{
  "uploads_dir": "%s",
  "upload_targets": [{"path": "foo.tbz2"}, {"path": "bar.tbz2"}]
}""" % uploads_dir

  @property
  def set_binhost_response(self):
    """Returns a fake SetBinhostResponse as a dict."""
    output_file = str(self.m.path['start_dir'].join('BINHOST.conf'))
    return '{"output_file": "%s"}' % output_file
