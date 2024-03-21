# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromite.api.sysroot import InstallPackagesResponse
from PB.chromiumos.common import RemoteexecArtifacts

from PB.recipe_modules.chromeos.remoteexec.remoteexec import RemoteexecProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/path',
    'recipe_engine/properties',
    'remoteexec',
]


def RunSteps(api):
  remoteexec_artifacts = RemoteexecArtifacts(log_files=['/tmp/TEST.log'])
  build_target_name = 'mock-amd64-generic'
  log_dir = str(api.path.mkdtemp(prefix='logs-'))

  # Test the case of missing arguments of install_pkg_response and log_dir.
  api.assertions.assertIsNone(
      api.remoteexec.process_artifacts(
          install_pkg_response=InstallPackagesResponse(),
          log_dir='',
          build_target_name=build_target_name,
      ))
  # Test the case of missing arguments of log_dir.
  api.assertions.assertIsNone(
      api.remoteexec.process_artifacts(
          install_pkg_response=InstallPackagesResponse(
              remoteexec_artifacts=remoteexec_artifacts),
          log_dir='',
          build_target_name=build_target_name,
      ))
  # Test the case of missing arguments of install_pkg_response.
  api.assertions.assertIsNone(
      api.remoteexec.process_artifacts(
          install_pkg_response=InstallPackagesResponse(),
          log_dir=log_dir,
          build_target_name=build_target_name,
      ))

  if not api.remoteexec.enable_logs_upload:
    # Test the disabled feature.
    api.assertions.assertIsNone(
        api.remoteexec.process_artifacts(
            install_pkg_response=InstallPackagesResponse(
                remoteexec_artifacts=remoteexec_artifacts),
            log_dir=log_dir,
            build_target_name=build_target_name,
        ))
  else:
    # Test the enabled feature.
    api.assertions.assertEqual(
        api.remoteexec.process_artifacts(
            install_pkg_response=InstallPackagesResponse(
                remoteexec_artifacts=remoteexec_artifacts),
            log_dir=log_dir,
            build_target_name=build_target_name,
        ),
        ['TEST.log'],
    )


def GenTests(api):
  yield api.test(
      'basic',
      api.properties(
          **{
              '$chromeos/remoteexec':
                  RemoteexecProperties(
                      enable_logs_upload=True,
                      reclient_version='release',
                      reproxy_cfg_file='reproxy_release.cfg',
                  )
          }))

  yield api.test(
      'disabled',
      api.properties(
          **{
              '$chromeos/remoteexec':
                  RemoteexecProperties(
                      reclient_version='release',
                      reproxy_cfg_file='reproxy_release.cfg',
                  )
          }),
  )
