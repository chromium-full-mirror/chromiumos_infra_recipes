# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for interacting with FindIt."""

from google.protobuf import json_format as jsonpb

from PB.chromiumos.common import PackageInfo

from recipe_engine import recipe_api

class CrosBisectApi(recipe_api.RecipeApi):
  """A module for interacting with FindIt."""

  def __init__(self, findit_bisect, *args, **kwargs):
    super(CrosBisectApi, self).__init__(*args, **kwargs)
    self._findit_bisect = findit_bisect

  def set_bisect_builder(self, build_target_name):
    """Sets the BISECT_BUILDER output property.

    Sets the BISECT_BUILDER output property to the name of the builder FindIt
    should invoke if the build fails and bisection is required.

    Args:
      build_target_name (str): build target name to set the bisect builder for.
    """
    res = self.m.step('set_bisect_builder', cmd=None)
    res.presentation.properties['BISECT_BUILDER'] = build_target_name + '-bisect'

  def _create_failures_payload(self, failed_packages):
    """Creates and returns the failures payload used by FindIt.

    Args:
      failed_packages (list[PackageInfo]): list of PackageInfo representing the
          failed packages.
    Returns:
      dict: failures payload used by FindIt to identify failures and later
          echo them back during bisection builds.
    """
    failures = []
    for pkg in failed_packages:
      failures.append({
          'rule': 'emerge',
          'output_targets': [jsonpb.MessageToJson(pkg)]
      })
    return {'failures': failures}

  def set_build_compile_failure(self, failed_packages):
    """Outputs failure of the failed packages for FindIt consumption.

    Outputs failure of the indicated packages for consumption by FindIt
    under the output property "BuildCompileFailureOutput". If there are no
    failed packages this method outputs nothing.

    Args:
      failed_packages (list[PackageInfo]): list of PackageInfo representing the
          failed packages.
    """
    if not failed_packages:
      return
    payload = self._create_failures_payload(failed_packages)
    res = self.m.step('set_build_compile_failure', cmd=None)
    res.presentation.properties['build_compile_failure_output'] = payload

  def get_packages(self):
    """Returns packages to build as specified by FindIt or empty list.

    Returns the packages to build as specified by a FindIt invocation or an
    empty list if this run was not invoked as a bisection build.

    Returns:
      list[PackageInfo]: list of packages to build as specified by FindIt
    """
    serialized_targets = self._findit_bisect.get('targets', [])
    return [jsonpb.Parse(st, PackageInfo()) for st in serialized_targets]
