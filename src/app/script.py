import base64
import quopri
import socket
import ssl
import sys
from dataclasses import dataclass

prefix = "A"
counter = 1


@dataclass
class cl_arguments:
    ssl: bool
    server: str
    port: int
    lower_bound: int
    upper_bound: int
    user: str
    valid: bool


arguments = cl_arguments(ssl=False, server="", port=143, lower_bound=1, upper_bound=-1, user="", valid=True)


@dataclass
class Letter:
    id: int
    to_address: str
    from_address: str
    subject: str
    date: str
    size: int
    attachments: list


def decode(line, from_to=False):
    parts = line.strip()
    parts = line.split("?")
    charset, encoding, content = parts[1], parts[2], parts[3]
    if encoding == "B":
        content = base64.b64decode(content).decode(charset)
    elif encoding == "Q":
        content = quopri.decodestring(content)

    if from_to:
        email_address = line.split("<")[1][:-1]
        return content + f" <{email_address}>"
    return content


def create_sock():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((arguments.server, arguments.port))
    ssl_sock = sock
    if arguments.ssl:
        ssl_sock = ssl.create_default_context().wrap_socket(sock, server_hostname=arguments.server)
    hello = ssl_sock.recv(1024).decode()
    print('S: ' + hello)
    return ssl_sock


def process_server_answer(answ):
    answer = answ.split(" ")
    match answer[1]:
        case "OK":
            return
        case "BAD":
            print("some syntax error occurred, please check your input. If you sure it is correct, contact developer")
            print(answ)
            quit(-2)
        case "NO":
            print(
                "some failure occurred, probably server refuses connection without ssl, please use --ssl command and try again")
            print(answ)
            quit(-3)


def send(sock, request, show=True):
    global counter
    request = prefix + str(counter) + " " + request
    sock.send(bytes(request + '\r\n', 'utf-8'))
    response = []
    while len(response) == 0 or response[-1].split(" ")[0] != prefix + str(counter):
        cur_block = sock.recv(1024).decode()
        cur_block = list(filter(lambda x: x != "", cur_block.split("\r\n")))
        for line in cur_block:
            response.append(line)
    response = "\r\n".join(response)
    process_server_answer(response)
    counter += 1
    return response


help_msg = """script for parsing email box with imap
Arguments:
-h|--help - prints help (this message)
--ssl - enables connection with ssl, disabled by default
-s|--server [server_address:[port]] - this command specifies imap server address (domain name or ip), port is optional, 143 by default
-n [N1 [N2]] - this command specifies range (N1 >= 1, N2 >= N1), in which script should parse letters, lower bound is necessary, upper is optional, script parse all letters by default
-u|--user [user_name] - this command specifies name (email) of box that you want to parse
"""


def process_arguments(a):
    if len(a) == 1:
        print(help_msg)
        quit(0)
    for i, arg in enumerate(a):
        match arg:
            case "-h", "--help":
                print(help_msg)
                quit(0)
            case "--ssl":
                arguments.ssl = True
            case '-s' | "--server":
                address = a[i + 1].split(":")
                arguments.server = address[0]
                if len(address) > 1:
                    try:
                        arguments.port = address[1]
                    except TypeError:
                        print("your port in not a number, please try again")
                        quit(-1)
            case "-n":
                lower_bound = a[i + 1]
                if lower_bound.isnumeric():
                    arguments.lower_bound = int(lower_bound)
                    try:
                        upper_bound = a[i + 2]
                        if upper_bound.isnumeric():
                            arguments.upper_bound = int(upper_bound)
                    except IndexError:
                        pass
                else:
                    arguments.valid = False
            case "-u" | "--user":
                arguments.user = a[i + 1]

    if arguments.valid:
        if arguments.server != "" and arguments.user != "":
            if arguments.ssl:
                arguments.port = 993
            return arguments
    else:
        print("your arguments is not valid, check --help and try again")
        quit(-1)


def login(sock):
    print("--login in process, enter your password--")
    pswd = input()
    send(sock, "LOGIN " + args.user + " " + pswd, False)


def parse_headers(letter, headers):
    headers = headers.split("\r\n")[1:-2]
    for i, header in enumerate(headers):
        header = header.split(":")
        if len(header) == 1:
            continue
        value = [header[1]]
        k = i
        while k + 1 < len(headers) and len(headers[k + 1].split(':')) == 1:
            value.append(headers[i + 1])
            k += 1
        match header[0]:
            case "Date":
                letter.date = ":".join(header[1:4])
            case "From":
                letter.from_address = "".join([decode(x, True) for x in value])
            case "To":
                letter.to_address = "".join([decode(x, True) for x in value])
            case "Subject":
                letter.subject = "".join([decode(x) for x in value])


def parse_attach(attach):
    attach = list(filter(lambda x: x != '' and x != " ", attach.replace('"', " ").split(" ")))
    attachment = {"name": "", "size": ""}
    for i, word in enumerate(attach):
        if word == "name":
            attachment["name"] = attach[i + 1]
        if word == "base64":
            attachment["size"] = attach[i + 1]
    return attachment


def parse_attachments(letter, structure):
    structure = structure.split('("text" "plain" ("charset" "cp1251") NIL NIL "7bit" 1 0 NIL NIL NIL NIL)')[:-1]
    attachments = []
    for attach in structure:
        attachments.append(parse_attach(attach))
    letter.attachments = attachments
    return letter


def parse_letters(us):
    letters_count = send(us, "SELECT Inbox").split("\r\n")[1].split(" ")[1]
    if arguments.upper_bound > int(letters_count) or arguments.upper_bound == -1:
        arguments.upper_bound = int(letters_count)
    for i in range(arguments.lower_bound, arguments.upper_bound):
        letter = Letter
        letter.id = i
        headers = send(us, "FETCH " + str(i) + " (BODY[HEADER.FIELDS (Date From To Subject)])")
        parse_headers(letter, headers)
        letter.size = send(us, "FETCH " + str(i) + " (RFC822.Size)").split("\r\n")[0].split(" ")[-1].replace(")", "")
        structure = send(us, "FETCH " + str(i) + " BODYSTRUCTURE").split("\r\n")[0][28:-29]
        letter = parse_attachments(letter, structure)
        print_letter(letter)


def print_letter(letter):
    result = [
        f"Letter {letter.id}: From:{letter.from_address}, To:{letter.to_address}, Subject:{letter.subject}, Size: {letter.size} Date:{letter.date}\r\nAttachments ({len(letter.attachments)}):"]
    for attach in letter.attachments:
        result.append(f"\r\nName: {attach['name']}, Size: {attach['size']}")
    print("".join(result) + "\r\n")


if __name__ == "__main__":
    args = process_arguments(sys.argv)
    user_socket = create_sock()
    login(user_socket)
    parse_letters(user_socket)
    send(user_socket, "LOGOUT")
