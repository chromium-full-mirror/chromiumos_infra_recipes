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
      build (Build): The build to describe.

    Returns:
      str: A string describing the build.
    """
    return '%s.%s.%s' % (build.builder.project, build.builder.bucket,
                         build.builder.builder)

  def get_commit_title(self, commit):
    """Get a string to describe the commit.

    This is typically the first line of the commit message.

    Args:
      commit (Commit): The commit in question. See recipe_modules/git/api.py

    Returns:
      str: The commit title.
    """
    lines = [l.strip() for l in commit.message.splitlines() if l.strip()]
    assert lines, 'unexpected empty commit message: %s' % commit.message
    return lines[0]
