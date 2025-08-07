sudo su

git clone https://gitlab.com/roeylalazar/uniapp.git
cd uniapp
git checkout main
cd uni-server/src
rmdir OCR
git clone https://github.com/ireman/OCR.git

cd OCR
wget https://benmodels.s3.eu-west-3.amazonaws.com/cyrus_classifier_with_shai_data_ver3.pt -4
wget https://benmodels.s3.eu-west-3.amazonaws.com/Detectron2model.pth -4
cd ..

cd ..

apt update
apt install docker-compose -y
docker-compose build && docker-compose up &

