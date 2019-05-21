# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = ['recipe_engine/assertions', 'analysis_service']

from PB.chromite.api.sysroot import InstallPackagesRequest, InstallPackagesResponse

from google.protobuf import json_format

# Test JSON protos.
INSTALL_PACKAGES_REQUEST = """
{
   "sysroot":{
      "path":"/a/b/c"
   }
}
"""

INSTALL_PACKAGES_RESPONSE = """
{
   "failed_packages":[
      {
         "package_name":"A package"
      }
   ]
}
"""


def RunSteps(api):
  install_packages_request = json_format.Parse(INSTALL_PACKAGES_REQUEST,
                                               InstallPackagesRequest())
  install_packages_response = json_format.Parse(INSTALL_PACKAGES_RESPONSE,
                                                InstallPackagesResponse())
  api.analysis_service.publish_event(request=install_packages_request,
                                     response=install_packages_response)

  # Pass in the request and response backwards, shouldn't work in this case
  # because the types are wrong.
  api.assertions.assertRaises(ValueError, api.analysis_service.publish_event,
                              request=install_packages_response,
                              response=install_packages_request)


def GenTests(api):
  yield api.test('basic')
