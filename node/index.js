const io = require("socket.io");
const server = io.listen(3000);
const fetch = require('node-fetch');

server.on("connection", function (socket) {
    console.log("user connected");
    socket.emit("welcome", "hello man");
    socket.on("authenticate_request", function (message) {
        fetch("http://localhost:8000/api/1/users/" + message.user + "/totp-auth/" + message.key).then(response => {
            let status = response.status;
            if (status === 200) {
                response.json().then(json => {
                    console.log("user " + message.user + " (" + socket.id + ") connected");
                    if (json.is_waiter) socket.join('waiters');
                    if (json.is_manager) socket.join('managers');
                    if (json.is_admin) socket.join('admins');
                });
                socket.emit("authenticate_result", "success")
            } else {
                console.log("user connection failed, disconnecting");
                socket.emit("authenticate_result", "fail");
                socket.disconnect();
            }
        });
    });
    socket.on('disconnect', function () {
        console.log("user disconnected")
    })
});

const interval = setInterval(function() {
    server.to('waiters').emit("waiters-ping", "Hello there");
    server.to('managers').emit("managers-ping", "Hello there");
    server.to('admins').emit("admins-ping", "Hello there");
}, 5000);
