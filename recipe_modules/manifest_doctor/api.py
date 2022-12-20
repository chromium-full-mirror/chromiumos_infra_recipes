# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API wrapping the manifest_doctor tool."""

import six

from recipe_engine import recipe_api


class ManifestDoctorApi(recipe_api.RecipeApi):
  """A module for calling manifest_doctor."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._properties = properties

  def initialize(self):
    """Initializes the module."""
    self._manifest_doctor_path = None

    self._manifest_doctor_cipd_package = six.ensure_str(
        self._properties.manifest_doctor_cipd_package.encode('utf-8') or
        "chromiumos/infra/manifest_doctor/${platform}")

    default_ref = "staging" if self.m.cros_infra_config.is_staging else "prod"
    self._manifest_doctor_cipd_ref = six.ensure_str(
        self._properties.manifest_doctor_cipd_ref.encode('utf-8') or
        default_ref)

  def __call__(self, cmd, step_name=None, **kwargs):
    """Call manifest_doctor with the given args.

    Args:
      cmd: Command to be run with manifest_doctor.
      step_name (str): Message to use for step. Optional.
      kwargs: Keyword arguments for recipe_engine/step.
    """
    self._ensure_manifest_doctor()
    self.m.step(step_name or 'run manifest_doctor',
                [self._manifest_doctor_path] + cmd, **kwargs)

  def _ensure_manifest_doctor(self):
    """Ensure the manifest_doctor cli is installed."""
    if self._manifest_doctor_path:
      return  # pragma: nocover

    with self.m.step.nest('ensure manifest_doctor'):
      with self.m.context(infra_steps=True):
        cipd_dir = self.m.path['start_dir'].join('cipd')

        pkgs = self.m.cipd.EnsureFile()
        pkgs.add_package(self._manifest_doctor_cipd_package,
                         self._manifest_doctor_cipd_ref)
        self.m.cipd.ensure(cipd_dir, pkgs)

        self._manifest_doctor_path = cipd_dir.join('manifest_doctor')
