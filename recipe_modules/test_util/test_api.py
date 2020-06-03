# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API to simplify testing Chrome OS recipes.

This module provides helpers to make testing Chrome OS recipes simpler and more
consistent.
"""

from collections import namedtuple
from recipe_engine import recipe_test_api

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2


class TestUtilApi(recipe_test_api.RecipeTestApi):
  """Helpers for testing Chrome OS Recipes."""

  def test_build(self, cq=False, dry_run=False, bot_size='large',
                 extra_changes=None, exe=None, input_properties=None,
                 create_time=None, start_time=None, update_time=None,
                 end_time=None, **kwargs):
    """Return a buildbucket step_data for a typical build.

    This differs from the buildbucket/test_api.py ci_build() and try_build() in
    that we tweak things to reflect chromeos.

    Args:
      cq (bool): whether this is a CQ triggered job, vs scheduled.
      dry_run (bool): Whether this is a dry_run (used only when |cq|=True).
      bot_size (str): Chrome OS bot_size dimension for the builder.
      extra_changes (list[GerritChange]): additional changes to add.
      exe (common_pb2.Executable): Executable for the build.  (passed to
          buildbucket.build)
      input_properties: dictionary of input properties, or None.
      create_time (seconds): Create time (passed to buildbucket.build).
      start_time (seconds): Start time (only in the returned message).
      update_time (seconds): Update time (only in the returned message).
      end_time (seconds): End time (only in the returned message).
      **kwargs: see buildbucket/test_api.py

    Returns:
      An object with attributes:
        message: buildbucket.Build message.
        build: Step_data for the build.
    """
    input_properties = input_properties or {}
    _test_build_return = namedtuple('_test_build_return', ['message', 'build'])
    kwargs.setdefault('project', 'chromeos')
    kwargs.setdefault('bucket', 'cq' if cq else 'postsubmit')
    kwargs.setdefault('builder', 'amd64-generic-' + kwargs['bucket'])
    kwargs.setdefault(
        'git_repo',
        'https://chrome-internal.googlesource.com/chromeos/manifest-internal')
    func = (
        self.m.buildbucket.try_build_message
        if cq else self.m.buildbucket.ci_build_message)

    msg = func(**kwargs)
    msg.input.gerrit_changes.extend(extra_changes or [])
    if bot_size:
      msg.infra.swarming.bot_dimensions.extend(
          [common_pb2.StringPair(key='bot_size', value=bot_size)])

    if create_time:
      msg.create_time.seconds = create_time
    if exe:
      msg.exe.cipd_package = exe.cipd_package
      msg.exe.cipd_version = exe.cipd_version
    msg.input.properties.update(input_properties)
    ret = self.m.buildbucket.build(msg)
    if cq:
      ret += self.m.cq(dry_run=dry_run, full_run=not dry_run)

    # These fields only go in the message since they are not present in
    # api.buildbucket.build.
    if start_time:
      msg.start_time.seconds = start_time
    if update_time:
      msg.update_time.seconds = update_time
    if end_time:
      msg.end_time.seconds = end_time

    return _test_build_return(msg, ret)
