# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for performing various manipulations on ChromeOS manifests."""

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/cipd',
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'bot_cost',
    'cros_infra_config',
    'cros_source',
    'repo',
    'workspace_util',
]

from PB.recipes.chromeos.manifest_doctor import ManifestDoctorProperties

PROPERTIES = ManifestDoctorProperties


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
  with api.step.nest('validate properties'):
    if not properties.min_milestone:
      raise StepFailure("min_milestone required")

  manifest_doctor_path = ensure_manifest_doctor(api, properties)
  if len(properties.buildspec_watch_paths) > 0:
    with api.step.nest("create external buildspecs"):
      cmd = [manifest_doctor_path, "public-buildspec"]
      cmd += ["--paths", ",".join(properties.buildspec_watch_paths)]
      if properties.push:
        cmd += ["--push"]

      api.step("run manifest_doctor", cmd)

  if len(properties.buildspec_watch_paths_legacy) > 0:
    with api.step.nest("create external buildspecs (legacy)"):
      cmd = [manifest_doctor_path, "public-buildspec"]
      cmd += ["--paths", ",".join(properties.buildspec_watch_paths_legacy)]
      cmd += ["--legacy"]
      if properties.push:
        cmd += ["--push"]

      api.step("run manifest_doctor", cmd)

  if len(properties.project_buildspec_watch_paths) > 0:
    with api.step.nest("create partner buildspecs"):
      cmd = [manifest_doctor_path, "project-buildspec"]
      cmd += ["--paths", ",".join(properties.project_buildspec_watch_paths)]
      cmd += ["--min_milestone", properties.project_buildspec_min_milestone]
      cmd += ["--projects", ",".join(properties.project_buildspecs)]
      if properties.push:
        cmd += ["--push"]

      api.step("run manifest_doctor", cmd)

  with api.bot_cost.build_cost_context(), api.workspace_util.setup_workspace():
    api.cros_source.ensure_synced_cache()
    api.cros_source.checkout_tip_of_tree()

    with api.step.nest("branch local manifests"):
      with api.context(cwd=api.workspace_util.workspace_path):
        all_projects = api.repo.project_infos()
      project_paths = []
      for project in all_projects:
        if project.name.startswith(
            "chromeos/project/") or project.name.startswith(
                "chromeos/program/"):
          project_paths.append(project.path)

      nproc = api.step(
          "nproc", ["nproc"], stdout=api.raw_io.output_text(),
          step_test_data=lambda: api.raw_io.test_api.stream_output(
              '8\n')).stdout.strip()

      cmd = [manifest_doctor_path, "branch-local-manifest"]
      cmd += ["--chromeos_checkout", api.workspace_util.workspace_path]
      cmd += ["--min_milestone", properties.min_milestone]
      cmd += ["--projects", ",".join(project_paths)]
      cmd += ["-j", nproc]

      if properties.push:
        cmd += ["--push"]
      api.step("run manifest_doctor", cmd)


def GenTests(api):
  yield api.test(
      'no-min_milestone',
      api.post_check(post_process.StepFailure, 'validate properties'),
  )

  yield api.test(
      'basic',
      api.properties(
          **{
              "min_milestone": 90,
              "buildspec_watch_paths": ["release/", "test/"],
              "buildspec_watch_paths_legacy": ["buildspecs/"],
              "project_buildspec_watch_paths":
                  ["full/buildspecs/", "buildspecs/"],
              "project_buildspec_min_milestone": 90,
              "project_buildspecs": ["galaxy/", "foo/bar"],
          }),
      api.repo.project_infos_step_data(
          'branch local manifests', data=[
              dict(project='chromeos/program/galaxy',
                   path='src/program/galaxy'),
              dict(project='chromeos/project/galaxy/milkyway',
                   path='src/project/galaxy/milkyway'),
              dict(project='chromeos/foo', path='src/foo'),
          ]),
      api.post_check(post_process.StepCommandContains,
                     'create external buildspecs.run manifest_doctor',
                     ['--paths', 'release/,test/']),
      api.post_check(post_process.StepCommandContains,
                     'create external buildspecs (legacy).run manifest_doctor',
                     ['--paths', 'buildspecs/']),
      api.post_check(
          post_process.StepCommandContains,
          'create partner buildspecs.run manifest_doctor', [
              '--paths', 'full/buildspecs/,buildspecs/', '--min_milestone',
              '90', '--projects', 'galaxy/,foo/bar'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'branch local manifests.run manifest_doctor',
          ['--projects', 'src/program/galaxy,src/project/galaxy/milkyway']),
      api.post_check(post_process.StepCommandContains,
                     'branch local manifests.run manifest_doctor',
                     ['--min_milestone', '90']),
      api.post_check(post_process.StepCommandContains,
                     'branch local manifests.run manifest_doctor', ['-j', '8']),
  )

  yield api.test(
      'push',
      api.properties(
          **{
              "push": True,
              "min_milestone": 90,
              "buildspec_watch_paths": ["release/", "test/"],
              "buildspec_watch_paths_legacy": ["buildspecs/"],
              "project_buildspec_watch_paths":
                  ["full/buildspecs/", "buildspecs/"],
              "project_buildspec_min_milestone": 90,
              "project_buildspecs": ["galaxy/", "foo/bar"],
          }),
      api.repo.project_infos_step_data(
          'branch local manifests', data=[
              dict(project='chromeos/program/galaxy',
                   path='src/program/galaxy'),
              dict(project='chromeos/project/galaxy/milkyway',
                   path='src/project/galaxy/milkyway'),
              dict(project='chromeos/foo', path='src/foo'),
          ]),
      api.post_check(post_process.StepCommandContains,
                     'create external buildspecs.run manifest_doctor',
                     ['--push']),
      api.post_check(post_process.StepCommandContains,
                     'create external buildspecs (legacy).run manifest_doctor',
                     ['--push']),
      api.post_check(post_process.StepCommandContains,
                     'create partner buildspecs.run manifest_doctor',
                     ['--push']),
      api.post_check(
          post_process.StepCommandContains,
          'branch local manifests.run manifest_doctor',
          ['--projects', 'src/program/galaxy,src/project/galaxy/milkyway']),
      api.post_check(post_process.StepCommandContains,
                     'branch local manifests.run manifest_doctor', ['--push']),
  )

  yield api.test(
      'with-ref',
      api.properties(
          **{
              "min_milestone":
                  90,
              "manifest_doctor_cipd_package":
                  "chromiumos/infra/manifest_doctor_foo",
              "manifest_doctor_cipd_ref":
                  "bar"
          }),
      api.post_check(post_process.StepCommandContains,
                     'ensure manifest_doctor.ensure_installed',
                     ['chromiumos/infra/manifest_doctor_foo bar']),
  )
