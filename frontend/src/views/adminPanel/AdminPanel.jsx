import UsersList from "./UsersList";

export default function AdminPanel() {
  return (
    <div className="p-8 min-h-screen">
      <h1 className="text-3xl font-bold mb-6 text-center">Admin Panel</h1>

      <div className="mb-10">
        <h2 className="text-2xl font-semibold mb-4">Users</h2>
        <UsersList />
      </div>
    
    </div>
  );
}
