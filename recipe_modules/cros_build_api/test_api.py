# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test responses for build API endpoints."""

from collections import namedtuple
import json

from recipe_engine import recipe_test_api
from .api import CrosBuildApiApi


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
  def android_service_responses(self):
    """Generate responses for AndroidService."""
    ret = {
        'MarkStable': jsonify(status='MARK_STABLE_STATUS_SUCCESS'),
    }
    return ret

  @property
  def artifact_service_responses(self):
    """Generate responses for ArtifactsService."""
    _uploaded_path = lambda name: dict(path=self.path(name), location=2)

    ret = {
        'FetchPinnedGuestImageUris':
            jsonify(pinned_images=[
                dict(filename='filename', uri='https://example.com/filename')
            ]),
        'BuildSetup':
            jsonify(build_relevance="UNKNOWN"),
        'Get':
            jsonify(
                artifacts=dict(
                    legacy=dict(artifacts=[
                        dict(artifact_type="EBUILD_LOGS",
                             paths=[_uploaded_path('log.tar.gz')])
                    ]), toolchain=dict(artifacts=[
                        dict(artifact_type="UNVERIFIED_CHROME_LLVM_ORDERFILE",
                             paths=[_uploaded_path('orderfile')])
                    ]))),
    }
    # Legacy, migrating to Get.
    bundle_response = jsonify(artifacts=[{
        'path': self.path('tmp/artifact.tar.gz')
    }])
    bundle_endpoints = [
        'BundleImageZip',
        'BundleTestUpdatePayloads',
        'BundleAutotestFiles',
        'BundleTastFiles',
        'BundlePinnedGuestImages',
        'BundleFirmware',
        'BundleEbuildLogs',
        'BundleChromeOSConfig',
        'ExportCpeReport',
        'BundleImageArchives',
        'BundleFpmcuUnittests',
        'BundleGceTarball',
        'BundleDebugSymbols',
    ]
    ret.update({endpoint: bundle_response for endpoint in bundle_endpoints})
    return ret

  @property
  def binhost_service_responses(self):
    """Generate responses for BinhostService."""
    responses = {}
    responses['PrepareBinhostUploads'] = jsonify(
        uploads_dir=self.path('uploads/dir'), upload_targets=[{
            'path': 'foo.tbz2'
        }])
    responses['SetBinhost'] = jsonify(output_file=self.path('BINHOST.conf'))
    responses['Get'] = jsonify(binhosts=[
        {
            'uri': 'gs://bucket1/some/path',
            'package_index': 'PackageIndex'
        },
        {
            'uri': 'gs://bucket2/diff/path',
            'package_index': 'PackageIndex'
        },
    ])
    responses['GetPrivatePrebuiltAclArgs'] = jsonify(args=[
        {
            'arg': 'arg1',
            'value': 'value1'
        },
        {
            'arg': 'arg2',
            'value': 'value2'
        },
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
                "dependency_packages": [{
                    "category": "chromeos-base",
                    "package_name": "chrome-icu",
                    "version": "1-r52"
                }],
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
        ],
    )
    responses['List'] = jsonify(
        package_deps=[
            {
                "category": "chromeos-base",
                "package_name": "chrome-icu",
                "version": "1-r52"
            },
        ],
    )
    return responses

  @property
  def firmware_service_responses(self):
    """Generate responses for FirmwareService."""
    _uploaded_path = lambda name: dict(path=self.path(name), location=2)

    responses = {
        'BuildAllTotFirmware':
            jsonify(
                # TODO(b/172268309): Provide sample data.
            ),
        'TestAllTotFirmware':
            jsonify(
                # TODO(b/172268309): Provide sample data.
            ),
        'BuildAllFirmware':
            jsonify(
                # TODO(b/177907747): Provide sample data.
            ),
        'TestAllFirmware':
            jsonify(
                # TODO(b/177907747): Provide sample data.
            ),
        'BundleFirmwareArtifacts':
            jsonify(
                artifacts=dict(artifacts=[
                    dict(artifact_type="FIRMWARE_TARBALL",
                         location="PLATFORM_EC",
                         paths=[_uploaded_path('from_source.tar.bz2')]),
                    dict(artifact_type="FIRMWARE_TARBALL_INFO",
                         location="PLATFORM_EC",
                         paths=[_uploaded_path('fw_metadata.json')])
                ]),
            )
    }
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
  def method_service_responses(self):
    """Generate responses for MethodService."""
    methods = []
    responses_by_service = self.responses_by_service(
        include_method_service=False)
    for service, responses_by_method in responses_by_service.items():
      for method in responses_by_method.keys():
        methods.append({'method': "chromite.api.%s/%s" % (service, method)})
    methods.append({'method': 'chromite.api.MethodService/Get'})
    responses = {}
    responses['Get'] = jsonify(methods=methods,)
    return responses

  @property
  def package_service_responses(self):
    """Generate responses for PackageService."""
    responses = {}
    responses['BuildsChrome'] = jsonify(builds_chrome=True,)
    responses['GetBestVisible'] = jsonify(package_info={
        'package_name': 'package',
        'category': 'category',
        'version': 'version'
    })
    responses['GetChromeVersion'] = jsonify(version='version',)
    responses['GetTargetVersions'] = jsonify(
        android_version='1',
        android_branch_version='git_rvc-arc',
        android_target_version='bertha',
        chrome_version='chrome_version',
        full_version='full_version',
        milestone_version='milestone_version',
        platform_version='platform_version',
    )
    responses['HasChromePrebuilt'] = jsonify(has_prebuilt=False)
    responses['HasPrebuilt'] = jsonify(has_prebuilt=False)
    # TODO(crbug/1086714): Add this when NeedsChromeSource is implemented.
    #responses['NeedsChromeSource'] = jsonify(
    #    needs_chrome_source=True,
    #    reasons=["LOCAL_UPREV", "NO_PREBUILT"],
    #)
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
  def payload_service_responses(self):
    """Generate responses for PayloadService."""
    responses = {}
    remote_uri = ('gs://test-bucket/canary-channel/zork/12345.0.0/payloads/'
                  'chromeos_12345.0.0_zork_canary-channel_full_test.bin-abc')
    responses['GeneratePayload'] = jsonify(
        success=True, local_path='/tmp/aohiwdadoi/delta.bin',
        remote_uri=remote_uri)
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
            'build_target': {
                'name': 'target'
            },
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
    responses['PrepareForBuild'] = jsonify(build_relevance="UNKNOWN")
    responses['BundleArtifacts'] = jsonify(artifacts_info=[
        dict(artifact_type="UNVERIFIED_CHROME_LLVM_ORDERFILE", artifacts=[
            {
                'path': 'my_output_artifact'
            },
        ])
    ])
    return responses

  @property
  def test_version(self):
    return CrosBuildApiApi.Version(1, 1, 0)

  @property
  def version_service_responses(self):
    """Generate responses for VersionService."""
    return dict(
        Get=jsonify(
            version=dict(major=self.test_version.major, minor=self.test_version
                         .minor, bug=self.test_version.bug)))

  def responses_by_service(self, include_method_service=True):
    """Map service name to a dictionary of responses by method name.

    Args:
      include_method_service (bool): used to include adding the endpoints of the
          MethodService to this map. This is a hack to allow
          `method_service_responses` to use this method to generate a full
          canned response without causing infinite recursion.
    """
    result = {
        'AndroidService': self.android_service_responses,
        'ArtifactsService': self.artifact_service_responses,
        'BinhostService': self.binhost_service_responses,
        'DependencyService': self.dependency_service_responses,
        'FirmwareService': self.firmware_service_responses,
        'ImageService': self.image_service_responses,
        'PackageService': self.package_service_responses,
        'PayloadService': self.payload_service_responses,
        'SdkService': self.sdk_service_responses,
        'SysrootService': self.sysroot_service_responses,
        'TestService': self.test_service_responses,
        'ToolchainService': self.toolchain_service_responses,
        'VersionService': self.version_service_responses,
    }
    if include_method_service:
      result['MethodService'] = self.method_service_responses
    return result

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
    responses_by_service = self.responses_by_service()
    if service not in responses_by_service:
      raise KeyError('No default test data for build API service '
                     '%s. %s' % (service, epilog))
    if method not in responses_by_service[service]:
      raise KeyError('No default test data for method '
                     '%s in service %s. %s' % (method, service, epilog))

    return responses_by_service[service][method]

  def set_api_return(self, parent_step_name, endpoint='', data='', iteration=1,
                     retcode=0, step_name=''):
    """Set the return from a Build API call.

    Args:
      parent_step_name (str): Name of the parent step, such as
        'prepare artifacts'.
      endpoint (str): Endpoint name, such as 'ImageService/Create'. Used to
        generate a step name.
      data (str): Build API response to return (JSON string).
      iteration (int): Which call this applies to for this step/endpoint.
      retcode (int): Return code for the Build API call.
      step_name (str): Name of the step given to the Build API call. If provided
        overrides the automatically generated name using the endpoint name.

    Returns:
      Step_data for the test.
    """
    # Calls after the first one have the iteration number appended.
    step_name = step_name or 'call chromite.api.%s' % endpoint
    iteration = '' if iteration == 1 else ' (%d)' % iteration
    substep = ('call build API script' if retcode else 'read output file')
    return self.step_data(
        '%s.%s%s.%s' % (parent_step_name, step_name, iteration, substep),
        self.m.file.read_raw(content=data), retcode=retcode)

  @recipe_test_api.mod_test_data
  @staticmethod
  def call_version_service(value):
    """Whether to call VersionService/Get in testing.

    Args:
      value (bool): if True, call VersionService/Get during testing.  If false,
      just use test_data or the default test answer, without calling the test
      method.

    Returns:
      (mod_test_data) to pass to api.test.
    """
    return value

  @recipe_test_api.mod_test_data
  @staticmethod
  def remove_endpoints(value):
    """Remove the given endpoints from the API.

    Args:
      value (set, dict, or list): endpoints to remove.  For example:
         ['ArtifactsService/Get']

    Returns:
      (mod_test_data) to pass to api.test.
    """
    assert not isinstance(value, str), 'endpoint must not be type str'
    return set('chromite.api.{}'.format(x).decode('utf-8') for x in value)
