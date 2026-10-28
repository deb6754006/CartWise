import { settleSignIn, useSignInRequest } from '../identity/requireSignIn';
import { SignInSheet } from './SignInSheet';

/** Renders SHEET-SIGNIN while a requireSignIn() call is waiting. Mount once per screen tree. */
export function SignInHost() {
  const request = useSignInRequest();
  return (
    <SignInSheet
      visible={request !== null}
      onSuccess={(session) => settleSignIn(session)}
      onCancel={() => settleSignIn(null)}
    />
  );
}
