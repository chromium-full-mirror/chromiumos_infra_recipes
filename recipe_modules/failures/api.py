# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for raising failures and presenting them in cute ways."""

from recipe_engine import recipe_api


class FailuresApi(recipe_api.RecipeApi):
  """A module for presenting errors and raising StepFailures."""

  def raise_failed_packages(self, failed_packages):
    """Display failed packages and raise a failure.

    Each package will be shown as a failed substep.

    Args:
      packages (list[chromiumos.common.PackageInfo]): The failed packages.

    Raises:
      StepFailure: If failed_packages is not empty.
    """
    if not failed_packages:
      return
    with self.m.step.nest('failed packages'):
      for failed_package in failed_packages:
        step = self.m.step(failed_package.package_name, None)
        step.presentation.status = self.m.step.FAILURE
    raise self.m.step.StepFailure(
        'Failed to install %d packages.' % len(failed_packages))
