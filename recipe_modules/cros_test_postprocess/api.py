# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections

from recipe_engine import recipe_api

DownloadedTestResult = collections.namedtuple('DownloadedTestResult',
                                              ['gs_path', 'local_path'])


class CrosTestPostProcessApi(recipe_api.RecipeApi):
  """Data structures used by the cros_test_postprocess recipe."""

  def downloaded_test_result(self, gs_path, local_path):
    """Create an object of DownloadedTestResult.

    The object created is passed to each post process api to consume.

    Args:
      gs_path: A string of GS path of test result to download.
      local_path: A Path object to save downloaded test result locally.

    Returns:
      A named tuple of (gs_path, local_path).
    """
    return DownloadedTestResult(gs_path=gs_path, local_path=local_path)
