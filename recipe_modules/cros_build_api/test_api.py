# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test responses for build API endpoints."""

import json

from recipe_engine import recipe_test_api


def jsonify(**kwargs):
  """Return the kwargs as a json string."""
  return json.dumps(kwargs)


class CrosBuildApiTestApi(recipe_test_api.RecipeTestApi):
  """Generate simple test data for all build API services.

  The data defined in this class is meant to serve as a simple default.
  Callers of cros_build_api may specify their own test data as they see
  fit.
  """

  def path(self, subpath):
    """Return the given subpath as a fully qualified path.

    Args:
      subpath (str): Relative path of interest.

    Returns:
      str: An absolute, qualified recipes path.
    """
    return str(self.m.path['start_dir'].join(subpath))

  @property
  def artifact_service_responses(self):
    """Generate responses for ArtifactsService."""
    bundle_response = jsonify(artifacts=[{
        'path': self.path('tmp/artifact.tar.gz')
    }])
    bundle_endpoints = [
        'BundleImageZip', 'BundleTestUpdatePayloads', 'BundleAutotestFiles',
        'BundleTastFiles', 'BundlePinnedGuestImages', 'BundleFirmware',
        'BundleEbuildLogs', 'BundleChromeOSConfig', 'ExportCpeReport',
        'BundleImageArchives',
    ]
    return {endpoint: bundle_response for endpoint in bundle_endpoints}

  @property
  def binhost_service_responses(self):
    """Generate responses for BinhostService."""
    responses = {}
    responses['PrepareBinhostUploads'] = jsonify(
        uploads_dir=self.path('uploads/dir'), upload_targets=[{
            'path': 'foo.tbz2'
        }])
    responses['SetBinhost'] = jsonify(output_file=self.path('BINHOST.conf'))
    responses['Get'] = jsonify(binhosts = [
        {'uri': 'gs://bucket1/some/path', 'package_index': 'PackageIndex'},
        {'uri': 'gs://bucket2/diff/path', 'package_index': 'PackageIndex'},
    ])
    responses['GetPrivatePrebuiltAclArgs'] = jsonify(args=[
        {'arg': 'arg1', 'value': 'value1'},
        {'arg': 'arg2', 'value': 'value2'},
    ])
    responses['RegenBuildCache'] = jsonify(modified_overlays=[{
        'path': self.path('chromiumos/src/overlay')
    }])
    return responses

  @property
  def dependency_service_responses(self):
    """Generate responses for DependencyService."""
    responses = {}
    responses['GetBuildDependencyGraph'] = jsonify(
        dep_graph={
          'package_deps': [{
            'dependency_source_paths': [{
              'path': 'some/source/dir',
            }],
          }],
        },
    )
    responses['GetToolchainPaths'] = jsonify(
        paths=[
            {
                'path': 'some/other/dir'
            },
        ],)
    return responses

  @property
  def image_service_responses(self):
    """Generate responses for ImageService."""
    responses = {}
    responses['Create'] = jsonify(
        success=True,
        images=[
            {
                'path': self.path('cros/src/build/images/base.bin'),
                'type': 'BASE'
            },
            {
                'path': self.path('cros/src/build/images/test.bin'),
                'type': 'TEST'
            },
        ],
        failed_packages=[],
    )
    responses['Test'] = jsonify(success=True)
    return responses

  @property
  def package_service_responses(self):
    """Generate responses for PackageService."""
    responses = {}
    responses['BuildsChrome'] = jsonify(
        builds_chrome=True,
    )
    responses['GetBestVisible'] = jsonify(
        package_info={
            'package_name': 'package',
            'category': 'category',
            'version': 'version'
        })
    responses['GetChromeVersion'] = jsonify(
        version='version',
    )
    responses['GetTargetVersions'] = jsonify(
        android_version='android_version',
        android_branch_version='android_branch_version',
        android_target_version='android_target_version',
        chrome_version='chrome_version',
        full_version='full_version',
        milestone_version='milestone_version',
        platform_version='platform_version',
    )
    responses['HasChromePrebuilt'] = jsonify(
        has_prebuilt=False,
    )
    responses['Uprev'] = jsonify(
        version='1.2.3', modified_ebuilds=[
            {
                'path': self.path('chromiumos/src/overlay/foo.ebuild')
            },
            {
                'path': self.path('chromiumos/src/private-overlay/bar.ebuild')
            },
        ])
    responses['UprevVersionedPackage'] = jsonify(responses=[
        dict(
            version='1.2.3', modified_ebuilds=[
                {
                    'path': self.path('chromiumos/src/overlay/foo.ebuild')
                },
                {
                    'path':
                        self.path('chromiumos/src/private-overlay/bar.ebuild')
                },
            ])
    ])
    return responses

  @property
  def sdk_service_responses(self):
    """Generate responses for SdkService."""
    responses = {}
    responses['Clean'] = '{}'
    responses['Create'] = jsonify(version={'version': 123})
    responses['Delete'] = '{}'
    responses['Unmount'] = '{}'
    responses['Update'] = jsonify(version={'version': 123})
    responses['CreateSnapshot'] = jsonify(
        snapshot_token={'value': 'TEST_SNAPSHOT'})
    responses['RestoreSnapshot'] = '{}'
    return responses

  @property
  def sysroot_service_responses(self):
    """Generate responses for SysrootService."""
    responses = {}
    responses['Create'] = jsonify(
        sysroot={
            'path': self.path('/build/target'),
            'build_target': {'name': 'target'},
        },
    )
    responses['InstallToolchain'] = jsonify(failed_packages=[])
    responses['InstallPackages'] = jsonify(failed_packages=[])
    return responses

  @property
  def test_service_responses(self):
    """Generate responses for TestService."""
    responses = {}
    responses['BuildTargetUnitTest'] = jsonify(
        tarball_path='tarball/path',
        failed_packages=[],
    )
    responses['ChromitePytest'] = '{}'
    responses['ChromiteUnitTest'] = '{}'
    responses['DebugInfoTest'] = '{}'
    responses['VmTest'] = '{}'
    responses['MoblabVmTest'] = '{}'
    return responses

  @property
  def toolchain_service_responses(self):
    """Generate responses for ToolchainService."""
    responses = {}
    responses['PrepareForBuild'] = jsonify(
        build_relevance="UNKNOWN"
    )
    responses['BundleArtifacts'] = jsonify(artifacts_info=[
        dict(
            artifact_type="UNVERIFIED_CHROME_LLVM_ORDERFILE", artifacts=[
                {'path': 'my_output_artifact'},
        ])
    ])
    return responses

  @property
  def responses_by_service(self):
    """Map service name to a dictionary of responses by method name."""
    return {
        'ArtifactsService': self.artifact_service_responses,
        'BinhostService': self.binhost_service_responses,
        'DependencyService': self.dependency_service_responses,
        'ImageService': self.image_service_responses,
        'PackageService': self.package_service_responses,
        'SdkService': self.sdk_service_responses,
        'SysrootService': self.sysroot_service_responses,
        'TestService': self.test_service_responses,
        'ToolchainService': self.toolchain_service_responses,
    }

  def response_for_endpoint(self, endpoint):
    """Return a fake response for the endpoint, if any.

    Args:
      endpoint (str): Fully qualified endpoint to get test response data for.

    Returns:
      str: JSON string containing fake response data for the endpoint.
    """
    service, method = endpoint.split('/')
    service = service.split('.')[-1]

    epilog = (
        'By convention, all build API calls must supply test data. '
        'You must either set test_output_data on your call to the build API '
        'or you must edit recipe_modules/cros_build_api/test_api.py to include '
        'test data for your endpoint.')
    if service not in self.responses_by_service:
      raise KeyError('No default test data for build API service '
                     '%s. %s' % (service, epilog))
    if method not in self.responses_by_service[service]:
      raise KeyError('No default test data for method '
                     '%s in service %s. %s' % (method, service, epilog))

    return self.responses_by_service[service][method]
