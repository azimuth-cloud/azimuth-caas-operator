terraform {
  required_version = ">= 0.14"

  # We need the OpenStack provider
  required_providers {
    openstack = {
      source = "terraform-provider-openstack/openstack"
      version = "~> 1.50.0"
    }
  }
}
