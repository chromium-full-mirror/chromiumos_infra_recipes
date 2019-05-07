# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API featuring shared helpers for naming things."""

from recipe_engine import recipe_api

class NamingApi(recipe_api.RecipeApi):
  """A module with helpers for naming things."""

  def get_build_title(self, build):
    """Get a string to describe the build.


    Args:
      * build (build_pb2.Build): The build to describe.

    Returns:
      A string describing the build.
    """
    return '%s/%s/%s/%d' % (build.builder.project, build.builder.bucket,
                            build.builder.builder, build.number or build.id)
