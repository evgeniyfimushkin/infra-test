terraform {
  required_providers {
    yandex = {
      source = "yandex-cloud/yandex"
    }
  }
  required_version = ">= 0.13"
}

provider "yandex" {
  zone = "ru-central1-d"
}

variable "vm_count" {
  type    = number
  default = 2
}

resource "yandex_compute_disk" "boot-disk" {
  count    = var.vm_count
  name     = "boot-disk-${count.index + 1}"
  type     = "network-hdd"
  zone     = "ru-central1-d"
  size     = "20"
  image_id = "fd8e4gcflhhc7odvbuss"
}

resource "yandex_compute_instance" "vm" {
  count       = var.vm_count
  name        = "terraform${count.index + 1}"
  platform_id = "standard-v2"
  allow_stopping_for_update = true

  resources {
    cores  = 4
    memory = 4
  }

  boot_disk {
    disk_id = yandex_compute_disk.boot-disk[count.index].id
  }

  network_interface {
    subnet_id = yandex_vpc_subnet.subnet-1.id
    nat       = true
  }

  metadata = {
    ssh-keys  = "ubuntu:${file("~/.skotty/pubs/ssh_yubikey_legacy.pub")}"
    user-data = file("./user-data.txt")
  }
}

resource "yandex_vpc_network" "network-1" {
  name = "network1"
}

resource "yandex_vpc_subnet" "subnet-1" {
  name           = "subnet1"
  zone           = "ru-central1-d"
  network_id     = yandex_vpc_network.network-1.id
  v4_cidr_blocks = ["192.168.10.0/24"]
}

output "internal_ip_addresses" {
  value = [for vm in yandex_compute_instance.vm : vm.network_interface[0].ip_address]
}

output "external_ip_addresses" {
  value = [for vm in yandex_compute_instance.vm : vm.network_interface[0].nat_ip_address]
}

