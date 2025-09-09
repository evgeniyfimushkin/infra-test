#!/bin/bash

# TERRAFORM
#
#



cd ~/git/infra-test/terraform
terraform apply -auto-approve -input=false -no-color
terraform output -json > terraform_output.json


# KUBESPRAY
#
# 

for ip in $PUB1 $PUB2; do
  until ssh -o ConnectTimeout=5 $ip 'echo ok' 2>/dev/null; do
    echo "Waiting for $ip..."
    sleep 5
  done
done


PUB1=$(jq -r '.external_ip_address_vm_1.value' terraform_output.json)
PUB2=$(jq -r '.external_ip_address_vm_2.value' terraform_output.json)
PRIV1=$(jq -r '.internal_ip_address_vm_1.value' terraform_output.json)
PRIV2=$(jq -r '.internal_ip_address_vm_2.value' terraform_output.json)

cd ~/git/kubespray

cat > inventory/cluster/inventory.ini <<EOF
node1 ansible_host=${PUB1} ip=${PRIV1} etcd_member_name=etcd1
node2 ansible_host=${PUB2} ip=${PRIV2} etcd_member_name=etcd2

[kube_control_plane]
node1

[etcd:children]
kube_control_plane

[kube_node]
node1
node2
EOF

cp ./inventory.sample ./inventory/cluster
cp ./inventory/sample/group_vars/k8s_cluster/k8s-cluster.yml ./inventory/cluster/group_vars/k8s_cluster/k8s-cluster.yml
echo supplementary_addresses_in_ssl_keys: [$PUB1, $PUB2] >> ./inventory/cluster/group_vars/k8s_cluster/k8s-cluster.yml

ansible-playbook -i inventory/cluster/inventory.ini cluster.yml -b -v

ssh  -o StrictHostKeyChecking=no $PUB1 sudo cat /etc/kubernetes/admin.conf | sed "s/127.0.0.1/${PUB1}/g" > ~/.kube/config

# ISTIO
#
#
#istioctl install -y
#kubectl label namespace default istio-injection=enabled


# DEPLOY
#
#

kubectl wait --for=condition=Ready nodes --all --timeout=10s


cd ~/git/microservices-demo/release 
#kubectl apply -f kubernetes-manifests.yaml

# Deploy prometheus stack in the cluster
#
#
#helm install prometheus prometheus-community/kube-prometheus-stack


#Deploy ArgoCD

kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl apply -f ~/git/infra-test/application/application.yaml
