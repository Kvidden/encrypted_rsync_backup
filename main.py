#!/bin/python3
#Copyright (c) 2023, Mikael Kvist
#All rights reserved.
#
#This source code is licensed under the BSD-style license found in the
#LICENSE file in the root directory of this source tree.
import os
import tarfile
import gzip
import json
import sys
import base64
import io
from cryptography.fernet import Fernet
from datetime import datetime, timedelta
# sätter vilken arbetskatalogen är med os.path.dirname nedan
main_directory = os.path.dirname(os.path.abspath(__file__))

def cleaning_old_files(ServerBackupDir):
    # skapar variabel med epochtime för 4 veckor sedan
    four_weeks_ago = datetime.now() - timedelta(weeks=4)
    for filename in os.listdir(ServerBackupDir):
        # lägger ihop filnamnet ur listan med katalogen för att veta var filen ligger
        file_location = os.path.join(ServerBackupDir, filename)
        # med os.stat(filen).st_ctime tar man fram epoch tiden när filen skapades
        # detta i en try ifall man inte får fram datan så att inte allt crashar
        try:
            file_creation_time = datetime.fromtimestamp(os.stat(file_location).st_ctime)
            # ifall tiden för skapande är äldre än 4 veckor så ta bort filen
            if file_creation_time < four_weeks_ago:
                os.remove(file_location)
        except AttributeError:
            print(f"Kunde inte få fram tiden för {file_location}")

def rsync_to_server(enviroment_data, encrypted_tarfile):
    user = enviroment_data["SSHUser"]
    key = enviroment_data["SSHKey"]
    for host, port in zip(enviroment_data["Hosts"],enviroment_data["Ports"]):
        if os.system(f'ping -c 3 {host} > /dev/null') == 0:
            os.system(f'rsync -avz -e "ssh -p {port} -i {key}" {encrypted_tarfile} {user}@{host}:{encrypted_tarfile}')

def decrypt_tarfile(ServerBackupDir, key, encrypted_tarfile=None):
    # skapar fernet objektet för att decryptera så den kan användas vart som
    fernet_object = Fernet(key)
    # skapar en lista för vilka filer som finns i backupkatalogen
    EncryptedBackupFiles = os.listdir(ServerBackupDir)
    # ifall encrypted_tarfile finns med i listan så gå vidare med att decryptera
    while not encrypted_tarfile in EncryptedBackupFiles:
        print(f"Filen var ej angiven eller fanns ej.\nVälj bland följande filer:\n{EncryptedBackupFiles}")
        encrypted_tarfile = input("Vilken fil skall dekrypteras?: ")
    # skapar ett fernet objekt av nyckeln som är i byte som typ
    # dekrypterar tarfilen med fernet objektet
    with open(os.path.join(ServerBackupDir, encrypted_tarfile), "rb") as encrypted_data:
        decrypted_tarfile = encrypted_data.read()
        decrypted_tarfile = fernet_object.decrypt(decrypted_tarfile)
    targzfile = os.path.join(ServerBackupDir, encrypted_tarfile[:-4])
    with open(targzfile, "wb") as tar:
        tar.write(decrypted_tarfile)

def tar_and_encrypt(encrypted_tarfile, key):
    BackupList = []
    # skapar backuplistan genom att öppna filen backup.list
    with open(os.path.join(main_directory, "backuplist.txt"), "r") as backuplist:
        for line in backuplist:
            BackupList.append(line.strip())
    # efter frågat chatgpt så kan kan man köra de mesta i minnet för att slippa
    # spara till disk och således spara en okrypterad tarfil för att ta bort.
    tarfile_buffer = io.BytesIO()
    # öppnar namnet på tarfilen med write och genom tar.add
    with tarfile.open(fileobj=tarfile_buffer, mode='w:gz') as tar:
        for BackupPart in BackupList:
            # ifall Zabbix-Server finns med i BackupPart strängen så kör det under
            if "Zabbix-Server" in BackupPart:
                # skapar en sökväg där zabbix sql dump skall hamna, vilket är i katalogen som backas upp
                zabbix_sql = os.path.join(BackupPart, "zabbix.sql")
                # tar ut sql dump ur docker och placerar i Zabbix-Server
                os.system(f"docker exec -i postgres-server /usr/bin/pg_dumpall -U zabbix > {zabbix_sql}")
            # kör med os.path.exists() för att om filen inte finns så skippas den bara
            # och inget stannar upp, d.v.s if true tar.add
            if os.path.exists(BackupPart):
                tar.add(BackupPart)
    if os.path.exists(os.path.join(BackupPart, "zabbix.sql")):
        # finns dump av databasen så ta bort den
        os.remove(os.path.join(BackupPart, "zabbix.sql"))
    # skapar ett fernet objekt av nyckeln som är i byte som typ
    fernet_object = Fernet(key)
    # skapar en krypterad tarfil av datan i bufferen som skapades förut
    encrypted_tarfile_data = fernet_object.encrypt(tarfile_buffer.getvalue())
    # för att försäkra oss om att den okrypterade datan tas bort så stänger vi
    # och sedan sätter buffern till None även fast det är en lokal variabel, rather safe then sorry
    tarfile_buffer.close()
    tarfile_buffer = None
    # skriver encrypted_tarfile_data till encrypted_tarfile filen som en fil med bytes läge
    with open(encrypted_tarfile, "wb") as output_data:
        output_data.write(encrypted_tarfile_data)
    # även här tar vi och nollar encrypted_tarfile_data för att att vara säkra
    encrypted_tarfile_data = None
    # kollar ifall dump av databasen finns

def main():
    # öppnar .env filen och läser in datan som sedan läses in som json i en dict
    with open(os.path.join(main_directory, ".env"), "r", encoding='utf-8') as file:
        enviroment_data = json.load(file)
    # lite variabler som behövs
    dagens_datum = datetime.now().strftime('%Y-%m-%d-')
    CurrentServer = enviroment_data["CurrentServer"]
    BackupDir = enviroment_data["BackupDir"]
    # med os.path.join() så kan löser den med rätt oavsätt om man slutar med / eller ej
    # så behöver man inte tänka på eventuella sådana fel som kan ske
    ServerBackupDir = os.path.join(BackupDir, CurrentServer)
    # ifall inte katalogen finns, skapa katalogen, rather safe then sorry att ha med
    if not os.path.exists(ServerBackupDir):
        os.makedirs(ServerBackupDir)
    # cryptografin från chatgpt och verifierat med synkade nycklar och Fernet är ok
    # då det behövs en sträng för json så encodades bytes nyckeln till base64
    # som nu decodas från base64 tillbaka till bytes nyckeln
    EncryptionKey = base64.b64decode(enviroment_data["EncryptionKey"])
    # kollar ifall argument kommer med in
    if len(sys.argv) > 1:
        # kollar så det inte är för många argument
        if len(sys.argv) < 4:
            # ifall decrypt är första argumentet
            if sys.argv[1] == "decrypt":
                if len(sys.argv) > 2:
                    encrypted_tarfile = sys.argv[2]
                    decrypt_tarfile(ServerBackupDir,EncryptionKey,encrypted_tarfile)
                else:
                    decrypt_tarfile(ServerBackupDir,EncryptionKey)
            else:
                print("Felaktig argument\nGiltiga argument:\ndecrypt som kan följas av filnamnet om så önskas")
                exit(0)
        else:
            print("För många argument")
            exit(0)
    else:
        encrypted_tarfile = os.path.join(ServerBackupDir, dagens_datum + CurrentServer + ".tar.gz.enc")
        # matar in vart den krypterade tarfilen skall vara samt krypteringsnyckeln
        tar_and_encrypt(encrypted_tarfile, EncryptionKey)
        # synkar filen till backupserver(s)
        rsync_to_server(enviroment_data, encrypted_tarfile)
    # rensar ut backupfiler som är äldre än 1 månad för att hushålla på servern
    cleaning_old_files(ServerBackupDir)

if __name__ == "__main__":
    main()
