# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for invoking the per project buildspec tool."""

from recipe_engine import post_process

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'bot_cost',
    'cros_infra_config',
]

from PB.recipes.chromeos.project_buildspec import ProjectBuildspecProperties

PROPERTIES = ProjectBuildspecProperties

# See go/per-project-buildspecs for more context.


def ensure_manifest_doctor(api, properties):
  manifest_doctor_cipd_package = (
      properties.manifest_doctor_cipd_package.encode('utf-8') or
      "chromiumos/infra/manifest_doctor/${platform}")

  default_ref = "staging" if api.cros_infra_config.is_staging else "prod"
  manifest_doctor_cipd_ref = (
      properties.manifest_doctor_cipd_ref.encode('utf-8') or default_ref)

  with api.step.nest('ensure manifest_doctor'):
    with api.context(infra_steps=True):
      cipd_dir = api.path['start_dir'].join('cipd')

      pkgs = api.cipd.EnsureFile()
      pkgs.add_package(manifest_doctor_cipd_package, manifest_doctor_cipd_ref)
      api.cipd.ensure(cipd_dir, pkgs)

      return cipd_dir.join('manifest_doctor')


def RunSteps(api, properties):
  with api.bot_cost.build_cost_context():
    manifest_doctor_path = ensure_manifest_doctor(api, properties)
    with api.step.nest("create program/project buildspec(s)"):
      cmd = [manifest_doctor_path, "project-buildspec"]
      cmd += ["--buildspec", properties.buildspec]
      cmd += ["--projects", ",".join(properties.projects)]

      api.step("run manifest_doctor", cmd)


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          ProjectBuildspecProperties(buildspec='buildspecs/foo/1.2.3.xml',
                                     projects=['galaxy/milkyway', 'foo/*'])),
      api.post_check(post_process.StepCommandContains,
                     'create program/project buildspec(s).run manifest_doctor',
                     [
                         '--buildspec', 'buildspecs/foo/1.2.3.xml',
                         '--projects', 'galaxy/milkyway,foo/*'
                     ]),
  )

  yield api.test(
      'with-ref',
      api.properties(
          **{
              "manifest_doctor_cipd_package":
                  "chromiumos/infra/manifest_doctor_foo",
              "manifest_doctor_cipd_ref":
                  "bar"
          }),
      api.post_check(post_process.StepCommandContains,
                     'ensure manifest_doctor.ensure_installed',
                     ['chromiumos/infra/manifest_doctor_foo bar']),
  )
