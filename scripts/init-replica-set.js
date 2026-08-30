const replicaSetConfig = {
  _id: "rs0",
  members: [
    { _id: 0, host: "mongo1:27017", priority: 2 },
    { _id: 1, host: "mongo2:27017", priority: 1 },
    { _id: 2, host: "mongo3:27017", priority: 1 },
  ],
};

let initialized = false;

try {
  rs.status();
  initialized = true;
  print("Replica set is already initialized.");
} catch (error) {
  if (error.code === 94 || error.codeName === "NotYetInitialized") {
    print("Initializing replica set rs0...");
    printjson(rs.initiate(replicaSetConfig));
  } else {
    throw error;
  }
}

let ready = false;

for (let attempt = 1; attempt <= 90; attempt += 1) {
  try {
    const status = rs.status();
    const primaryCount = status.members.filter(
      (member) => member.stateStr === "PRIMARY",
    ).length;
    const secondaryCount = status.members.filter(
      (member) => member.stateStr === "SECONDARY",
    ).length;

    if (primaryCount === 1 && secondaryCount === 2) {
      ready = true;
      print(
        `Replica set ready after ${attempt} check(s); initialized=${initialized}.`,
      );
      printjson(
        status.members.map((member) => ({
          name: member.name,
          state: member.stateStr,
          health: member.health,
        })),
      );
      break;
    }
  } catch (error) {
    print(`Waiting for replica set: ${error.message}`);
  }

  sleep(1000);
}

if (!ready) {
  print("Replica set did not become healthy within 90 seconds.");
  try {
    printjson(rs.status());
  } catch (error) {
    print(error);
  }
  quit(1);
}

